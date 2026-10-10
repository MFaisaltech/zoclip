import hashlib
import os
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select, tuple_
from starlette.concurrency import run_in_threadpool

from zoclip.auth.dependencies import DB, CsrfSession, CurrentUser
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.rate_limit import rate_limit
from zoclip.credits.routes import OperationKey
from zoclip.media import service
from zoclip.media.models import Job, JobEvent, SourceVideo, UploadPart, UploadSession
from zoclip.media.schemas import (
    EventView,
    GenerateInput,
    Hash,
    ImportInput,
    JobView,
    PartView,
    ProcessInput,
    UploadInput,
    UploadView,
    VideoView,
)
from zoclip.media.storage import LocalStorage

router = APIRouter(prefix="/api/v1", tags=["media"])


def storage(request: Request) -> LocalStorage:
    return LocalStorage(request.app.state.settings.media_root)


def upload_view(db: DB, upload: UploadSession) -> UploadView:
    result = UploadView.model_validate(upload)
    if upload.state == "COMPLETE":
        count = (upload.expected_bytes + upload.part_bytes - 1) // upload.part_bytes
        result.received_parts = list(range(count))
        return result
    result.received_parts = list(
        db.scalars(
            select(UploadPart.number)
            .where(UploadPart.upload_id == upload.id)
            .order_by(UploadPart.number)
        )
    )
    return result


@router.post("/uploads", response_model=UploadView, status_code=201)
def initiate(
    data: UploadInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> UploadView:
    rate_limit(request, "media-admission", str(user.id))
    upload = service.initiate(db, user.id, data, key, request.app.state.settings, storage(request))
    result = upload_view(db, upload)
    db.commit()
    return result


@router.get("/uploads/{upload_id}", response_model=UploadView)
def get_upload(upload_id: UUID, db: DB, user: CurrentUser) -> UploadView:
    return upload_view(db, service.owned(db, UploadSession, user.id, upload_id))


@router.put(
    "/uploads/{upload_id}/parts/{part_number}",
    response_model=PartView,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def put_part(
    upload_id: UUID,
    part_number: int,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
    x_content_sha256: Annotated[Hash, Header()],
) -> PartView:
    owner, factory = user.id, request.app.state.session_factory
    db.rollback()  # Auth is complete; don't keep a DB connection during upload I/O.
    local, settings = storage(request), request.app.state.settings
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise ApiError(422, "invalid_content_type", "Part must be application/octet-stream.")

    def begin() -> tuple[UUID, int]:
        with factory() as transaction:
            result = service.claim_part(transaction, owner, upload_id, part_number, settings, local)
            transaction.commit()
            return result

    token, expected = await run_in_threadpool(begin)
    try:
        size, digest = 0, hashlib.sha256()
        with anyio.fail_after(60), local.create(token) as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > expected:
                    raise ApiError(413, "part_too_large", "Part exceeds its admitted size.")
                digest.update(chunk)
                await run_in_threadpool(output.write, chunk)
            await run_in_threadpool(output.flush)
            await run_in_threadpool(os.fsync, output.fileno())
        if size != expected or digest.hexdigest() != x_content_sha256:
            raise ApiError(422, "integrity_failed", "Part length or checksum differs.")

        def accept() -> PartView:
            with factory() as transaction:
                part = service.accept_part(
                    transaction,
                    owner,
                    upload_id,
                    part_number,
                    token,
                    size,
                    digest.hexdigest(),
                    local,
                )
                result = PartView(number=part.number, size_bytes=part.size, sha256=part.sha256)
                transaction.commit()
                return result

        return await run_in_threadpool(accept)
    except TimeoutError as exc:
        raise ApiError(408, "upload_timeout", "Part upload deadline exceeded.") from exc
    finally:

        def release_writer() -> None:
            with factory() as transaction:
                service.mutex(transaction, owner, cleanup=True)
                upload = service.owned(transaction, UploadSession, owner, upload_id, lock=True)
                if upload.write_token == token:
                    upload.write_token, upload.write_until = None, None
                transaction.commit()
            local.delete(token)

        # Client disconnect/cancellation must not skip lease cleanup.
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(release_writer)


@router.post("/uploads/{upload_id}/complete", response_model=JobView, status_code=202)
def complete(
    upload_id: UUID,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> JobView:
    job = service.finalize(db, user.id, upload_id, key, request.app.state.settings)
    result = JobView.model_validate(job)
    db.commit()
    return result


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: UUID, db: DB, user: CurrentUser, csrf: CsrfSession) -> Response:
    upload = service.owned(db, UploadSession, user.id, upload_id)
    service.delete_video(db, user.id, upload.video_id)
    db.commit()
    return Response(status_code=204)


@router.post("/videos/import-url", response_model=JobView, status_code=202)
def import_url(
    data: ImportInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> JobView:
    rate_limit(request, "media-admission", str(user.id))
    job = service.import_url(db, user.id, data, key, request.app.state.settings, storage(request))
    result = JobView.model_validate(job)
    db.commit()
    return result


@router.post("/jobs", response_model=JobView, status_code=202)
def process(
    data: ProcessInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> JobView:
    rate_limit(request, "media-admission", str(user.id))
    job = service.process(db, user.id, data, key, request.app.state.settings, storage(request))
    result = JobView.model_validate(job)
    db.commit()
    return result


@router.post("/videos/{video_id}/generate", response_model=JobView, status_code=202)
def generate(
    video_id: UUID,
    data: GenerateInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> JobView:
    """Canonical source-bound entrypoint; /jobs remains a compatible alias."""
    return process(
        ProcessInput(video_id=video_id, quote_id=data.quote_id), key, request, db, user, csrf
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: UUID, db: DB, user: CurrentUser) -> JobView:
    return JobView.model_validate(service.owned(db, Job, user.id, job_id))


@router.get("/jobs", response_model=list[JobView])
def jobs(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), before: UUID | None = None
) -> list[JobView]:
    query = select(Job).where(Job.user_id == user.id)
    if before:
        boundary = service.owned(db, Job, user.id, before)
        query = query.where(tuple_(Job.created_at, Job.id) < (boundary.created_at, boundary.id))
    return [
        JobView.model_validate(j)
        for j in db.scalars(query.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit))
    ]


@router.get("/jobs/{job_id}/events", response_model=list[EventView])
def events(
    job_id: UUID,
    db: DB,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=100),
    before: UUID | None = None,
) -> list[EventView]:
    service.owned(db, Job, user.id, job_id)
    query = select(JobEvent).where(JobEvent.job_id == job_id)
    if before:
        boundary = db.scalar(
            select(JobEvent).where(JobEvent.id == before, JobEvent.job_id == job_id)
        )
        if boundary is None:
            raise ApiError(404, "not_found", "Cursor not found.")
        query = query.where(
            tuple_(JobEvent.created_at, JobEvent.id) < (boundary.created_at, boundary.id)
        )
    return [
        EventView.model_validate(e)
        for e in db.scalars(
            query.order_by(JobEvent.created_at.desc(), JobEvent.id.desc()).limit(limit)
        )
    ]


@router.post("/jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: UUID, db: DB, user: CurrentUser, csrf: CsrfSession) -> JobView:
    job = service.cancel_job(db, user.id, job_id)
    db.flush()
    result = JobView.model_validate(job)
    db.commit()
    return result


@router.get("/videos", response_model=list[VideoView])
def videos(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), before: UUID | None = None
) -> list[VideoView]:
    query = select(SourceVideo).where(
        SourceVideo.user_id == user.id,
        SourceVideo.state != "DELETED",
        SourceVideo.expires_at > utcnow(),
    )
    if before:
        boundary = service.owned(db, SourceVideo, user.id, before)
        query = query.where(
            tuple_(SourceVideo.created_at, SourceVideo.id) < (boundary.created_at, boundary.id)
        )
    return [
        VideoView.model_validate(v)
        for v in db.scalars(
            query.order_by(SourceVideo.created_at.desc(), SourceVideo.id.desc()).limit(limit)
        )
    ]


@router.get("/videos/{video_id}", response_model=VideoView)
def get_video(video_id: UUID, db: DB, user: CurrentUser) -> VideoView:
    video = service.owned(db, SourceVideo, user.id, video_id)
    if video.state == "DELETED" or video.expires_at <= utcnow():
        raise ApiError(404, "not_found", "Retained media not found.")
    return VideoView.model_validate(video)


@router.get(
    "/videos/{video_id}/content",
    response_class=StreamingResponse,
    responses={200: {"content": {"video/mp4": {}, "video/webm": {}}}},
)
def content(video_id: UUID, request: Request, db: DB, user: CurrentUser) -> StreamingResponse:
    # Authorize under the same lock order as deletion, refreshing any cached row.
    # Opening the descriptor is the download's authorization/linearization point.
    service.mutex(db, user.id)
    video = service.owned(db, SourceVideo, user.id, video_id, lock=True)
    if video.state != "READY" or video.expires_at <= utcnow():
        raise ApiError(404, "not_found", "Retained media not found.")
    # Open while serializing with deletion, then stream the descriptor (no public paths).
    local = storage(request)
    try:
        handle = local.open(video.object_id)
    except FileNotFoundError as exc:
        raise ApiError(404, "not_found", "Retained media not found.") from exc
    try:
        db.commit()
    except BaseException:
        handle.close()
        raise

    def chunks():  # type: ignore[no-untyped-def]
        try:
            while chunk := handle.read(65536):
                yield chunk
        finally:
            handle.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="source-video"'},
    )


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: UUID, db: DB, user: CurrentUser, csrf: CsrfSession) -> Response:
    service.delete_video(db, user.id, video_id)
    db.commit()
    return Response(status_code=204)
