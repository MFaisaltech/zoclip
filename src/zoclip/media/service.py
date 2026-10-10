"""Short PostgreSQL transactions compose media admission with Phase 2 accounting."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.core.config import Settings
from zoclip.core.db import Base, utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import Quote
from zoclip.media.importer import validate_url
from zoclip.media.models import (
    Job,
    JobEvent,
    Outbox,
    Project,
    SourceVideo,
    StorageObject,
    StoragePool,
    UploadPart,
    UploadSession,
)
from zoclip.media.schemas import ImportInput, ProcessInput, UploadInput
from zoclip.media.storage import LocalStorage

ACTIVE = {"QUEUED", "RUNNING", "CANCEL_REQUESTED", "WAITING_ENGINE", "SUGGESTIONS_READY"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELED"}


def required[Model: Base](db: Session, model: type[Model], key: UUID) -> Model:
    result = db.get(model, key)
    if result is None:
        raise ApiError(503, "inconsistent_state", "Required durable record is unavailable.")
    return result


def owned(db: Session, model, owner: UUID, key: UUID, *, lock: bool = False):  # type: ignore[no-untyped-def]
    statement = select(model).where(model.id == key, model.user_id == owner)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    value = db.scalar(statement)
    if value is None:
        raise ApiError(404, "not_found", "Resource not found.")
    return value


def mutex(db: Session, owner: UUID, *, cleanup: bool = False) -> None:
    money.lock_wallet(db, owner, active_required=not cleanup)
    if db.scalar(select(StoragePool).where(StoragePool.id == 1).with_for_update()) is None:
        raise ApiError(503, "storage_unavailable", "Storage admission is unavailable.")


def capacity(db: Session, settings: Settings, storage: LocalStorage, additional: int = 0) -> None:
    outstanding, retained = db.execute(
        select(
            func.coalesce(
                func.sum(StorageObject.reserved_bytes - StorageObject.materialized_bytes), 0
            ),
            func.coalesce(func.sum(StorageObject.reserved_bytes), 0),
        ).where(StorageObject.deleted.is_(False))
    ).one()
    if (
        additional < 0
        or storage.free_bytes() - outstanding - additional < settings.media_headroom_bytes
        or retained + additional > settings.media_retained_bytes
    ):
        raise ApiError(507, "insufficient_capacity", "Private storage capacity unavailable.")


def event(db: Session, job: Job, state: str, code: str | None = None) -> None:
    allowed = {
        "QUEUED": {"RUNNING", "CANCELED", "FAILED"},
        "RUNNING": {
            "COMPLETED",
            "FAILED",
            "WAITING_ENGINE",
            "CANCEL_REQUESTED",
            "QUEUED",
            "SUGGESTIONS_READY",
        },
        "CANCEL_REQUESTED": {"CANCELED"},
        "WAITING_ENGINE": {"CANCELED", "FAILED", "QUEUED"},
        "SUGGESTIONS_READY": {"CANCELED", "FAILED"},
    }
    if job.state != state and state not in allowed.get(job.state, set()):
        raise ApiError(409, "invalid_transition", "Job transition is forbidden.")
    job.state, job.error_code = state, code
    db.add(JobEvent(job_id=job.id, state=state, code=code))


def queue_job(
    db: Session, owner: UUID, video: UUID, kind: str, key: str, payload: dict, request_hash: str
) -> Job:
    job = Job(
        id=uuid4(),
        user_id=owner,
        video_id=video,
        kind=kind,
        operation_key=key,
        request_hash=request_hash,
        payload=payload,
    )
    db.add(job)
    db.flush()
    db.add_all([Outbox(job_id=job.id, generation=0), JobEvent(job_id=job.id, state="QUEUED")])
    return job


def pending_gate(db: Session, settings: Settings) -> None:
    if (
        db.scalar(select(func.count()).select_from(Job).where(Job.state == "QUEUED")) or 0
    ) >= settings.media_pending_limit:
        raise ApiError(429, "queue_full", "The processing queue is full.")


def ingestion_gate(db: Session, owner: UUID, settings: Settings) -> None:
    # Free catalog must also have an explicit configured quota; no automatic allowance.
    money.active_price(db, owner)
    query = (
        select(func.count())
        .select_from(SourceVideo)
        .where(SourceVideo.state.in_({"UPLOADING", "IMPORTING", "VALIDATING"}))
    )
    if (db.scalar(query) or 0) >= settings.media_ingestion_limit or (
        db.scalar(query.where(SourceVideo.user_id == owner)) or 0
    ) >= settings.media_user_ingestion_limit:
        raise ApiError(429, "ingestion_limit", "Active ingestion limit reached.")
    pending_gate(db, settings)


def source(
    db: Session, owner: UUID, size: int, state: str, settings: Settings, storage: LocalStorage
) -> SourceVideo:
    reserve = 3 * size + 2 * 1024**3
    capacity(db, settings, storage, reserve)
    project = Project(user_id=owner)
    obj = StorageObject(user_id=owner, reserved_bytes=reserve)
    db.add_all([project, obj])
    db.flush()
    video = SourceVideo(
        user_id=owner,
        project_id=project.id,
        object_id=obj.id,
        state=state,
        expires_at=utcnow() + timedelta(seconds=settings.media_retention_seconds),
    )
    db.add(video)
    db.flush()
    return video


def initiate(
    db: Session, owner: UUID, data: UploadInput, key: str, settings: Settings, storage: LocalStorage
) -> UploadSession:
    mutex(db, owner)
    hashed = money.fingerprint(data.model_dump())
    old = db.scalar(
        select(UploadSession).where(
            UploadSession.user_id == owner, UploadSession.operation_key == key
        )
    )
    if old:
        money.same(old.request_hash, hashed)
        return old
    if data.size_bytes > settings.media_max_bytes:
        raise ApiError(413, "media_too_large", "Upload exceeds configured size.")
    ingestion_gate(db, owner, settings)
    video = source(db, owner, data.size_bytes, "UPLOADING", settings, storage)
    upload = UploadSession(
        user_id=owner,
        video_id=video.id,
        operation_key=key,
        request_hash=hashed,
        expected_bytes=data.size_bytes,
        sha256=data.sha256,
        part_bytes=settings.media_part_bytes,
        expires_at=utcnow() + timedelta(seconds=settings.media_upload_ttl_seconds),
    )
    db.add(upload)
    db.flush()
    return upload


def claim_part(
    db: Session,
    owner: UUID,
    upload_id: UUID,
    number: int,
    settings: Settings,
    storage: LocalStorage,
) -> tuple[UUID, int]:
    mutex(db, owner)
    upload = owned(db, UploadSession, owner, upload_id, lock=True)
    if upload.state != "OPEN" or upload.expires_at <= utcnow():
        raise ApiError(409, "upload_closed", "Upload is no longer writable.")
    expected = min(upload.part_bytes, upload.expected_bytes - number * upload.part_bytes)
    if number < 0 or expected <= 0:
        raise ApiError(422, "invalid_part", "Part number is outside this upload.")
    if upload.write_until and upload.write_until > utcnow():
        raise ApiError(409, "upload_busy", "Another part is being written; retry later.")
    capacity(db, settings, storage)
    token = uuid4()
    upload.write_token, upload.write_until = token, utcnow() + timedelta(seconds=180)
    return token, expected


def accept_part(
    db: Session,
    owner: UUID,
    upload_id: UUID,
    number: int,
    token: UUID,
    size: int,
    digest: str,
    storage: LocalStorage,
) -> UploadPart:
    mutex(db, owner)
    upload = owned(db, UploadSession, owner, upload_id, lock=True)
    if upload.state != "OPEN" or upload.write_token != token or upload.write_until <= utcnow():
        raise ApiError(409, "stale_upload", "Part writer lease expired.")
    part = db.scalar(
        select(UploadPart).where(UploadPart.upload_id == upload.id, UploadPart.number == number)
    )
    if part:
        if (part.sha256, part.size) != (digest, size):
            raise ApiError(409, "idempotency_conflict", "Existing part differs from request.")
    else:
        part = UploadPart(upload_id=upload.id, number=number, size=size, sha256=digest)
        db.add(part)
        db.flush()
        storage.promote(token, part.id)
        video = required(db, SourceVideo, upload.video_id)
        obj = required(db, StorageObject, video.object_id)
        obj.materialized_bytes += size
    upload.write_token, upload.write_until = None, None
    db.flush()
    return part


def finalize(db: Session, owner: UUID, upload_id: UUID, key: str, settings: Settings) -> Job:
    mutex(db, owner)
    upload = owned(db, UploadSession, owner, upload_id, lock=True)
    payload = {"upload_id": str(upload.id)}
    hashed = money.fingerprint(payload)
    old = db.scalar(select(Job).where(Job.user_id == owner, Job.operation_key == key))
    if old:
        money.same(old.request_hash, hashed)
        return old
    if (
        upload.state != "OPEN"
        or upload.expires_at <= utcnow()
        or (upload.write_until and upload.write_until > utcnow())
    ):
        raise ApiError(409, "upload_closed", "Upload is incomplete or busy.")
    parts = list(
        db.scalars(
            select(UploadPart).where(UploadPart.upload_id == upload.id).order_by(UploadPart.number)
        )
    )
    count = (upload.expected_bytes + upload.part_bytes - 1) // upload.part_bytes
    if (
        len(parts) != count
        or [p.number for p in parts] != list(range(count))
        or sum(p.size for p in parts) != upload.expected_bytes
    ):
        raise ApiError(409, "incomplete_upload", "All parts must be received before completion.")
    pending_gate(db, settings)
    upload.state = "FINALIZING"
    required(db, SourceVideo, upload.video_id).state = "VALIDATING"
    return queue_job(db, owner, upload.video_id, "VALIDATE", key, payload, hashed)


def import_url(
    db: Session, owner: UUID, data: ImportInput, key: str, settings: Settings, storage: LocalStorage
) -> Job:
    url = data.url.get_secret_value()
    validate_url(url, settings.media_allowed_import_hosts)
    mutex(db, owner)
    payload = {"url": url, "max_bytes": data.max_bytes, "rights_attested": True}
    hashed = money.fingerprint(payload)
    old = db.scalar(select(Job).where(Job.user_id == owner, Job.operation_key == key))
    if old:
        money.same(old.request_hash, hashed)
        return old
    if data.max_bytes > settings.media_max_bytes:
        raise ApiError(413, "media_too_large", "Import exceeds configured size.")
    ingestion_gate(db, owner, settings)
    video = source(db, owner, data.max_bytes, "IMPORTING", settings, storage)
    return queue_job(db, owner, video.id, "IMPORT", key, payload, hashed)


def process(
    db: Session,
    owner: UUID,
    data: ProcessInput,
    key: str,
    settings: Settings,
    storage: LocalStorage,
) -> Job:
    # Financial locks precede media locks everywhere. User lock serializes all mutations.
    money.lock_wallet(db, owner)
    hashed = money.fingerprint(data.model_dump())
    old = db.scalar(select(Job).where(Job.user_id == owner, Job.operation_key == key))
    if old:
        money.same(old.request_hash, hashed)
        return old
    video = owned(db, SourceVideo, owner, data.video_id)
    quote = owned(db, Quote, owner, data.quote_id)
    if video.state != "READY" or video.expires_at <= utcnow():
        raise ApiError(409, "source_not_ready", "A validated, retained source is required.")
    if quote.request["source_seconds"] != video.metadata_json["duration_seconds"]:
        raise ApiError(
            409, "quote_duration_mismatch", "Quote must use the validated source duration."
        )
    job_id = uuid4()
    reservation = money.reserve(
        db,
        owner,
        quote.id,
        job_id,
        "job-reserve:" + str(job_id),
        production=settings.app_env == "production",
    )
    mutex(db, owner)
    pending_gate(db, settings)
    if (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == owner, Job.kind == "PROCESS", Job.state.in_(ACTIVE))
        )
        or 0
    ) >= settings.media_user_processing_limit:
        raise ApiError(429, "processing_limit", "Active processing limit reached.")
    obj = required(db, StorageObject, video.object_id)
    extra = (
        2 * 1024**3
        + ((video.metadata_json["duration_seconds"] + 59) // 60)
        * quote.request["output_count"]
        * 32
        * 1024**2
    )
    capacity(db, settings, storage, extra)
    obj.reserved_bytes += extra
    job = Job(
        id=job_id,
        user_id=owner,
        video_id=video.id,
        kind="PROCESS",
        operation_key=key,
        request_hash=hashed,
        reservation_id=reservation.id,
        checkpoint={"estimated_credits": reservation.credits},
    )
    db.add(job)
    db.flush()
    db.add_all([Outbox(job_id=job.id, generation=0), JobEvent(job_id=job.id, state="QUEUED")])
    return job


def terminate(db: Session, job: Job, state: str, code: str | None = None) -> None:
    if job.kind == "PROCESS":
        from zoclip.ai.worker import finalize_pending

        finalize_pending(db, job, None)
    if job.reservation_id:
        money.finish(
            db,
            job.user_id,
            job.reservation_id,
            "job-release:" + str(job.id),
            success=False,
            evidence=str(job.id),
        )
    event(db, job, state, code)
    job.payload = {}  # Erase private import URL as soon as no longer needed.
    job.lease_token, job.lease_until = None, None
    video = required(db, SourceVideo, job.video_id)
    obj = required(db, StorageObject, video.object_id)
    if job.kind == "PROCESS":
        obj.reserved_bytes = obj.materialized_bytes
    elif state != "COMPLETED":
        if video.state != "DELETED":
            video.state = "FAILED"
        upload = db.scalar(select(UploadSession).where(UploadSession.video_id == video.id))
        if upload:
            upload.state = "CANCELED" if state == "CANCELED" else "FAILED"


def cancel_job(db: Session, owner: UUID, job_id: UUID) -> Job:
    mutex(db, owner, cleanup=True)
    job = owned(db, Job, owner, job_id, lock=True)
    if job.state == "RUNNING":
        event(db, job, "CANCEL_REQUESTED")
    elif job.state in {"QUEUED", "WAITING_ENGINE", "SUGGESTIONS_READY"}:
        terminate(db, job, "CANCELED")
    return job


def delete_video(db: Session, owner: UUID, video_id: UUID) -> SourceVideo:
    mutex(db, owner, cleanup=True)
    video = owned(db, SourceVideo, owner, video_id, lock=True)
    upload = db.scalar(select(UploadSession).where(UploadSession.video_id == video.id))
    if upload and upload.write_until and upload.write_until > utcnow():
        raise ApiError(409, "upload_busy", "Wait for the bounded part writer before deleting.")
    for job in db.scalars(
        select(Job).where(Job.video_id == video.id, Job.state.in_(ACTIVE)).with_for_update()
    ):
        if job.state == "RUNNING":
            event(db, job, "CANCEL_REQUESTED")
        elif job.state in {"QUEUED", "WAITING_ENGINE", "SUGGESTIONS_READY"}:
            terminate(db, job, "CANCELED")
    if upload and upload.state == "OPEN":
        upload.state = "CANCELED"
    video.state = "DELETED"  # Revoke reads now; cleanup waits for safe leases.
    return video
