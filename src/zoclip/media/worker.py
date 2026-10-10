"""RQ is transport only. Leases fence every publication and financial transition."""

import hashlib
import os
import random
import time
from datetime import timedelta
from uuid import UUID, uuid4

from redis import Redis
from rq import Queue
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as financial
from zoclip.credits.schemas import ConsumptionRules
from zoclip.media import service
from zoclip.media.importer import download
from zoclip.media.models import Job, Outbox, SourceVideo, StorageObject, UploadPart, UploadSession
from zoclip.media.probe import probe
from zoclip.media.storage import LocalStorage

LEASE_SECONDS = 900  # Longer than RQ timeout (660s) and bounded local stages (625s).


def retry_delay(attempts: int) -> float:
    """Bounded equal jitter; max three claims remains enforced separately."""
    ceiling = min(30, 2 ** min(max(attempts, 1), 5))
    return random.uniform(ceiling / 2, ceiling)


def claim(db: Session, job_id: UUID, generation: int) -> tuple[UUID, UUID] | None:
    initial = db.get(Job, job_id)
    if not initial:
        return None
    service.mutex(db, initial.user_id, cleanup=True)
    job = service.owned(db, Job, initial.user_id, job_id, lock=True)
    if job.state != "QUEUED" or job.generation != generation:
        return None
    owner = service.required(db, User, job.user_id)
    if owner.status != "active" or not owner.verified:
        service.terminate(db, job, "FAILED", "account_unavailable")
        return None
    if (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.state.in_({"RUNNING", "CANCEL_REQUESTED"}),
                Job.checkpoint["render_selection"].as_boolean().is_(True)
                if job.checkpoint.get("render_selection")
                else or_(
                    Job.checkpoint["render_selection"].as_boolean().is_(None),
                    Job.checkpoint["render_selection"].as_boolean().is_(False),
                ),
            )
        )
        or 0
    ) >= 1:
        return None  # One AI ingestion worker, even if an operator starts extra processes.
    video = service.required(db, SourceVideo, job.video_id)
    if video.state == "DELETED":
        service.terminate(db, job, "CANCELED")
        return None
    token = uuid4()
    job.lease_token = token
    job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
    job.heartbeat_at = utcnow()
    job.attempts += 1
    service.event(db, job, "RUNNING")
    return token, job.user_id


def current(db: Session, owner: UUID, job_id: UUID, token: UUID) -> Job:
    service.mutex(db, owner, cleanup=True)
    job = service.owned(db, Job, owner, job_id, lock=True)
    if (
        job.lease_token != token
        or not job.lease_until
        or job.lease_until <= utcnow()
        or job.state not in {"RUNNING", "CANCEL_REQUESTED"}
    ):
        raise ApiError(409, "stale_worker", "Worker no longer owns this job.")
    return job


def run_job(
    job_id: UUID, generation: int, factory: sessionmaker, settings: Settings, storage: LocalStorage
) -> None:
    with factory() as db:
        claimed = claim(db, job_id, generation)
        db.commit()
        if not claimed:
            return
        token, owner = claimed
        job = db.get(Job, job_id)
        kind, payload = job.kind, dict(job.payload)
        render_selected = bool(job.checkpoint.get("render_selection"))
        video = service.required(db, SourceVideo, job.video_id)
        object_id = video.object_id
        if kind == "VALIDATE":
            upload = db.get(UploadSession, UUID(payload["upload_id"]))
            expected_size, expected_hash = upload.expected_bytes, upload.sha256
            parts = [
                (p.id, p.size, p.sha256)
                for p in db.scalars(
                    select(UploadPart)
                    .where(UploadPart.upload_id == upload.id)
                    .order_by(UploadPart.number)
                )
            ]
        db.rollback()  # No transaction during files, DNS, HTTP or ffprobe.
    try:
        if kind == "RENDER" or render_selected:
            from zoclip.rendering.worker import run as render

            render(job_id, owner, token, factory, settings, storage)
            return
        if kind == "PROCESS":
            from zoclip.ai.worker import run

            run(job_id, owner, token, factory, settings, storage)
            return
        with factory() as db:
            job = current(db, owner, job_id, token)
            service.capacity(db, settings, storage)
            if job.state == "CANCEL_REQUESTED":
                service.terminate(db, job, "CANCELED")
                db.commit()
                return
            job.heartbeat_at = utcnow()
            db.commit()
        deadline = time.monotonic() + 600
        last_heartbeat = time.monotonic()

        def heartbeat() -> None:
            nonlocal last_heartbeat
            if time.monotonic() - last_heartbeat < 5:
                return
            with factory() as db:
                active = current(db, owner, job_id, token)
                if active.state == "CANCEL_REQUESTED":
                    raise ApiError(409, "job_canceled", "Cancellation requested.")
                active.heartbeat_at = utcnow()
                db.commit()
            last_heartbeat = time.monotonic()

        digest, size = hashlib.sha256(), 0
        with storage.create(token) as output:
            if kind == "IMPORT":
                size = download(
                    payload["url"],
                    settings.media_allowed_import_hosts,
                    output,
                    payload["max_bytes"],
                    progress=heartbeat,
                )
            else:
                for part_id, part_size, part_hash in parts:
                    part_digest, measured = hashlib.sha256(), 0
                    with storage.open(part_id) as source:
                        while chunk := source.read(65536):
                            heartbeat()
                            if time.monotonic() > deadline:
                                raise TimeoutError("assembly deadline")
                            measured += len(chunk)
                            size += len(chunk)
                            if measured > part_size or size > expected_size:
                                raise ApiError(
                                    422, "integrity_failed", "Upload integrity check failed."
                                )
                            digest.update(chunk)
                            part_digest.update(chunk)
                            output.write(chunk)
                    if measured != part_size or part_digest.hexdigest() != part_hash:
                        raise ApiError(422, "integrity_failed", "Upload integrity check failed.")
                if size != expected_size or digest.hexdigest() != expected_hash:
                    raise ApiError(422, "integrity_failed", "Upload integrity check failed.")
            output.flush()
            os.fsync(output.fileno())
        metadata = probe(storage.path(token), settings.ffprobe_binary)
        if kind == "IMPORT":
            with storage.open(token) as source:
                digest = hashlib.sha256()
                while chunk := source.read(65536):
                    if time.monotonic() > deadline:
                        raise TimeoutError("digest deadline")
                    digest.update(chunk)
        metadata.update({"size_bytes": size, "sha256": digest.hexdigest()})
        with factory() as db:
            job = current(db, owner, job_id, token)
            if job.state == "CANCEL_REQUESTED":
                service.terminate(db, job, "CANCELED")
            else:
                service.capacity(db, settings, storage)
                price = financial.active_price(db, owner)
                rules = ConsumptionRules.model_validate(price.rules)
                if metadata["duration_seconds"] > rules.max_source_seconds:
                    raise ApiError(
                        422, "plan_duration_exceeded", "Source exceeds active plan duration."
                    )
                storage.promote(token, object_id)
                video = service.required(db, SourceVideo, job.video_id)
                video.state, video.metadata_json = "READY", metadata
                obj = db.get(StorageObject, object_id)
                obj.materialized_bytes = size
                obj.reserved_bytes = size
                # Materialized part files still reduce actual filesystem free space
                # until cleanup; they have no remaining future disk commitment.
                upload = db.scalar(select(UploadSession).where(UploadSession.video_id == video.id))
                if upload:
                    upload.state = "COMPLETE"
                job.checkpoint = {"validated_object": str(object_id), "sha256": metadata["sha256"]}
                service.event(db, job, "COMPLETED")
                job.payload = {}
                job.lease_token, job.lease_until = None, None
            db.commit()
    except Exception as exc:
        with factory() as db:
            if kind == "PROCESS":
                financial.lock_wallet(db, owner, active_required=False)
            try:
                job = current(db, owner, job_id, token)
            except ApiError:
                return  # Expired worker cannot publish, retry or release someone else's hold.
            if job.state == "CANCEL_REQUESTED":
                if kind == "PROCESS":
                    from zoclip.ai.worker import finalize_pending

                    finalize_pending(db, job, storage)
                service.terminate(db, job, "CANCELED")
            elif kind == "PROCESS":
                from zoclip.ai.worker import handle_error

                handle_error(db, job, storage, exc)
            elif isinstance(exc, (OSError, TimeoutError)) and job.attempts < 3:
                service.event(db, job, "QUEUED", "source_temporarily_unavailable")
                job.generation += 1
                job.lease_token, job.lease_until = None, None
                db.add(
                    Outbox(
                        job_id=job.id,
                        generation=job.generation,
                        dispatch_until=utcnow() + timedelta(seconds=retry_delay(job.attempts)),
                    )
                )
            else:
                service.terminate(
                    db, job, "FAILED", exc.code if isinstance(exc, ApiError) else "ingestion_failed"
                )
            db.commit()
    finally:
        storage.delete(token)


def execute(job_id: str, generation: int) -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        run_job(
            UUID(job_id),
            generation,
            sessionmaker(engine, expire_on_commit=False),
            settings,
            LocalStorage(settings.media_root),
        )
    finally:
        engine.dispose()


def dispatch(factory: sessionmaker, redis: Redis, *, limit: int = 10) -> int:
    """Claim short DB lease, enqueue outside transaction, acknowledge afterwards.

    A crash after enqueue redelivers; PostgreSQL worker claim is authoritative.
    Every pending delivery is resent periodically until the DB job is claimed,
    so Redis loss/queue eviction cannot strand a committed job.
    """
    delivered = 0
    for _ in range(limit):
        with factory() as db:
            now = utcnow()
            row = db.scalar(
                select(Outbox)
                .join(Job, Job.id == Outbox.job_id)
                .where(
                    Job.state == "QUEUED",
                    Job.generation == Outbox.generation,
                    or_(Outbox.dispatch_until.is_(None), Outbox.dispatch_until < now),
                    or_(
                        Outbox.dispatched_at.is_(None),
                        Outbox.dispatched_at < now - timedelta(seconds=60),
                    ),
                )
                .order_by(Outbox.created_at)
                .with_for_update(of=Outbox, skip_locked=True)
                .limit(1)
            )
            if not row:
                break
            token, row_id, job_id, generation = uuid4(), row.id, row.job_id, row.generation
            delivery_job = db.get(Job, job_id)
            queue = "render" if delivery_job.checkpoint.get("render_selection") else "ai"
            row.dispatch_token, row.dispatch_until = token, now + timedelta(seconds=30)
            db.commit()
        # Random delivery ID avoids Redis registry collisions; claim deduplicates.
        Queue(queue, connection=redis).enqueue(
            "zoclip.media.worker.execute",
            str(job_id),
            generation,
            job_id="ingest-" + uuid4().hex,
            job_timeout=660,
            result_ttl=60,
            failure_ttl=300,
            ttl=120,
        )
        with factory() as db:
            row = db.get(Outbox, row_id, with_for_update=True)
            if row.dispatch_token == token:
                row.dispatched_at, row.dispatch_until = utcnow(), None
                db.commit()
        delivered += 1
    return delivered


def recover(factory: sessionmaker, storage: LocalStorage | None = None) -> int:
    with factory() as db:
        ids = list(
            db.scalars(
                select(Job.id)
                .where(Job.state.in_({"RUNNING", "CANCEL_REQUESTED"}), Job.lease_until < utcnow())
                .limit(100)
            )
        )
    for job_id in ids:
        with factory() as db:
            initial = db.get(Job, job_id)
            if initial.kind == "PROCESS":
                financial.lock_wallet(db, initial.user_id, active_required=False)
            service.mutex(db, initial.user_id, cleanup=True)
            job = service.owned(db, Job, initial.user_id, job_id, lock=True)
            if job.state not in {"RUNNING", "CANCEL_REQUESTED"} or job.lease_until >= utcnow():
                continue
            # PROCESS recovery replays checkpoints, never fresh admission keys for a lost call.
            if job.checkpoint.get("render_selection"):
                from zoclip.rendering.worker import handle_error as render_error

                render_error(db, job, TimeoutError("worker_lost"))
            elif job.state == "CANCEL_REQUESTED":
                if job.kind == "PROCESS":
                    from zoclip.ai.worker import finalize_pending

                    finalize_pending(db, job, storage)
                service.terminate(db, job, "CANCELED")
            elif job.kind == "PROCESS":
                from zoclip.ai.worker import handle_error

                handle_error(db, job, None, TimeoutError("worker_lost"), recovering=True)
            elif job.attempts >= 3:
                service.terminate(db, job, "FAILED", "worker_lost")
            else:
                service.event(db, job, "QUEUED", "worker_recovered")
                job.generation += 1
                job.lease_token, job.lease_until = None, None
                db.add(Outbox(job_id=job.id, generation=job.generation))
            db.commit()
    return len(ids)
