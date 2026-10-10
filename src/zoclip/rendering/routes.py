from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from zoclip.auth.dependencies import DB, CsrfSession, CurrentUser
from zoclip.core.errors import ApiError
from zoclip.credits.routes import OperationKey
from zoclip.media import service as media
from zoclip.media.models import Job
from zoclip.media.schemas import JobView
from zoclip.media.storage import LocalStorage
from zoclip.rendering import service
from zoclip.rendering.models import Clip, RenderOutput
from zoclip.rendering.schemas import (
    ClipView,
    CreateClip,
    OutputView,
    Preferences,
    RenderInput,
    Selection,
)

router = APIRouter(prefix="/api/v1", tags=["rendering"])


def view(db: DB, clip: Clip) -> ClipView:
    return ClipView(
        id=clip.id,
        video_id=clip.video_id,
        job_id=clip.job_id,
        revision=clip.revision,
        created_at=clip.created_at,
        preferences=Preferences.model_validate(service.revision(db, clip).preferences),
    )


@router.post("/clips", response_model=ClipView, status_code=201)
def create(data: CreateClip, db: DB, user: CurrentUser, csrf: CsrfSession) -> ClipView:
    # Candidate uniqueness is the idempotency key for draft creation.
    clip = service.create(db, user.id, data.suggestion_id)
    result = view(db, clip)
    db.commit()
    return result


@router.get("/clips", response_model=list[ClipView])
def listing(
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: UUID | None = None,
) -> list[ClipView]:
    from sqlalchemy import tuple_

    from zoclip.core.db import utcnow
    from zoclip.media.models import SourceVideo

    query = (
        select(Clip)
        .join(SourceVideo)
        .where(
            Clip.user_id == user.id, SourceVideo.state == "READY", SourceVideo.expires_at > utcnow()
        )
    )
    if before:
        cursor = media.owned(db, Clip, user.id, before)
        query = query.where(tuple_(Clip.created_at, Clip.id) < (cursor.created_at, cursor.id))
    return [
        view(db, c)
        for c in db.scalars(query.order_by(Clip.created_at.desc(), Clip.id.desc()).limit(limit))
    ]


@router.get("/clips/{clip_id}", response_model=ClipView)
def detail(clip_id: UUID, db: DB, user: CurrentUser) -> ClipView:
    clip = media.owned(db, Clip, user.id, clip_id)
    service.retained(db, user.id, clip.video_id)
    return view(db, clip)


@router.patch("/clips/{clip_id}", response_model=ClipView)
def edit(
    clip_id: UUID,
    data: Preferences,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
    if_match: Annotated[str, Header(pattern=r'^"[1-9][0-9]{0,3}"$')],
) -> ClipView:
    clip = service.edit(db, user.id, clip_id, int(if_match.strip('"')), data)
    result = view(db, clip)
    db.commit()
    return result


@router.post("/jobs/{job_id}/renders", response_model=JobView, status_code=202)
def select_clips(
    job_id: UUID,
    data: Selection,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
    key: OperationKey,
) -> Job:
    settings = request.app.state.settings
    job = service.select_clips(
        db, user.id, job_id, data.clip_ids, key, settings, LocalStorage(settings.media_root)
    )
    db.commit()
    return job


@router.post("/clips/{clip_id}/render", response_model=JobView, status_code=202)
def render(
    clip_id: UUID,
    data: RenderInput,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
    key: OperationKey,
) -> Job:
    settings = request.app.state.settings
    job = service.rerender(
        db, user.id, clip_id, data, key, settings, LocalStorage(settings.media_root)
    )
    db.commit()
    return job


@router.get("/clips/{clip_id}/renders", response_model=list[OutputView])
def outputs(clip_id: UUID, db: DB, user: CurrentUser) -> list[OutputView]:
    clip = media.owned(db, Clip, user.id, clip_id)
    service.retained(db, user.id, clip.video_id)
    return [
        OutputView(
            id=o.id,
            clip_id=o.clip_id,
            revision=o.revision,
            job_id=o.job_id,
            state=o.state,
            metadata=o.metadata_json,
            created_at=o.created_at,
        )
        for o in db.scalars(
            select(RenderOutput)
            .where(RenderOutput.clip_id == clip.id)
            .order_by(RenderOutput.revision.desc())
            .limit(101)
        )
    ]


@router.get(
    "/clips/{clip_id}/download",
    response_class=StreamingResponse,
    responses={200: {"content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}}}},
)
def download(
    clip_id: UUID,
    request: Request,
    db: DB,
    user: CurrentUser,
    revision: Annotated[int | None, Query(ge=1, le=101)] = None,
) -> StreamingResponse:
    media.mutex(db, user.id)
    clip = media.owned(db, Clip, user.id, clip_id, lock=True)
    service.retained(db, user.id, clip.video_id)
    output = db.scalar(
        select(RenderOutput)
        .join(Job)
        .where(
            RenderOutput.clip_id == clip.id,
            RenderOutput.revision == (revision or clip.revision),
            RenderOutput.state == "COMPLETE",
            Job.state == "COMPLETED",
        )
    )
    if not output:
        raise ApiError(404, "not_found", "A completed export is required.")
    try:
        file = LocalStorage(request.app.state.settings.media_root).open(output.object_id)
    except FileNotFoundError as exc:
        raise ApiError(503, "output_unavailable", "Export is temporarily unavailable.") from exc
    try:
        db.commit()
    except Exception:
        file.close()
        raise

    def chunks():  # type: ignore[no-untyped-def]
        try:
            while chunk := file.read(65536):
                yield chunk
        finally:
            file.close()

    return StreamingResponse(
        chunks(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{clip.id}-r{output.revision}.mp4"'},
    )
