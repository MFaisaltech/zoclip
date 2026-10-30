"""One selected clip per lease; receipts and settlement share PostgreSQL transactions."""

import math
import sys
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from zoclip.ai.models import ClipSuggestion, Transcript
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.generation_access import require_generation_access
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, PlanPrice, Quote, SpendAttempt
from zoclip.media import service as media
from zoclip.media.models import Job, Outbox, SourceVideo, StorageObject
from zoclip.media.storage import LocalStorage
from zoclip.rendering import engine, service
from zoclip.rendering.models import Clip, RenderOutput
from zoclip.rendering.schemas import Preferences


def cpu() -> float:
    if sys.platform == "win32":
        return time.monotonic() * 2  # Conservative two-thread upper bound on Windows.
    import resource

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def reconcile(db: Session, job: Job, units: int | None = None) -> None:
    key = job.checkpoint.get("render_attempt")
    if key:
        attempt = media.required(db, SpendAttempt, UUID(key))
        if attempt.state == "HELD":
            money.record_spend(
                db,
                job.user_id,
                attempt.id,
                units=attempt.units if units is None else max(1, units),
                outcome="success",
                evidence="render-cpu:" + str(attempt.id),
            )


def finalize(db: Session, job: Job) -> None:
    reconcile(db, job)  # Lost worker costs remain conservatively recorded, never erased.
    for output in db.scalars(select(RenderOutput).where(RenderOutput.job_id == job.id)):
        if output.state == "PENDING":
            output.state = "FAILED"
        if output.state != "COMPLETE":
            obj = media.required(db, StorageObject, output.object_id)
            # Keep the commitment until cleanup removes any crash-promoted file.
            obj.updated_at = utcnow()


def handle_error(db: Session, job: Job, exc: Exception, *, units: int | None = None) -> None:
    reconcile(db, job, units)
    output = db.scalar(
        select(RenderOutput)
        .where(RenderOutput.job_id == job.id, RenderOutput.state == "PENDING")
        .order_by(RenderOutput.created_at)
        .limit(1)
    )
    if job.state == "CANCEL_REQUESTED":
        media.terminate(db, job, "CANCELED")
        return
    if output:
        output.failures += 1
    transient = isinstance(exc, (OSError, TimeoutError))
    if transient and output and output.failures < 3:
        from zoclip.media.worker import retry_delay

        media.event(db, job, "QUEUED", "render_retry")
        job.generation += 1
        job.lease_token, job.lease_until = None, None
        job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "render_attempt"}
        db.add(
            Outbox(
                job_id=job.id,
                generation=job.generation,
                dispatch_until=utcnow() + timedelta(seconds=retry_delay(output.failures)),
            )
        )
    else:
        media.terminate(
            db, job, "FAILED", exc.code if isinstance(exc, ApiError) else "render_failed"
        )


def run(
    job_id: UUID,
    owner: UUID,
    token: UUID,
    factory: sessionmaker,
    settings: Settings,
    storage: LocalStorage,
) -> None:
    from zoclip.media.worker import current

    require_generation_access(settings, owner)
    last = 0.0
    started = cpu()

    def heartbeat() -> None:
        nonlocal last
        if time.monotonic() - last < 1:
            return
        with factory() as db:
            job = current(db, owner, job_id, token)
            video = media.required(db, SourceVideo, job.video_id)
            if (
                job.state == "CANCEL_REQUESTED"
                or video.state != "READY"
                or video.expires_at <= utcnow()
            ):
                raise ApiError(409, "job_canceled", "Render canceled or source expired.")
            job.heartbeat_at = utcnow()
            db.commit()
        last = time.monotonic()

    try:
        with factory() as db:
            job = current(db, owner, job_id, token)
            if job.state == "CANCEL_REQUESTED":
                media.terminate(db, job, "CANCELED")
                db.commit()
                return
            media.capacity(db, settings, storage)
            reconcile(db, job)  # Interrupted prior claim: charge its bounded ceiling before retry.
            output = db.scalars(
                select(RenderOutput)
                .where(RenderOutput.job_id == job.id, RenderOutput.state == "PENDING")
                .order_by(RenderOutput.created_at)
            ).first()
            if not output:
                raise ApiError(409, "missing_output", "Render has no pending revision.")
            clip = media.required(db, Clip, output.clip_id)
            prefs = Preferences.model_validate(
                service.revision(db, clip, output.revision).preferences
            )
            service.validate(db, clip, prefs)
            video = media.required(db, SourceVideo, clip.video_id)
            assert clip.suggestion_id is not None
            suggestion = media.required(db, ClipSuggestion, clip.suggestion_id)
            transcript = media.required(db, Transcript, suggestion.transcript_id)
            words = transcript.data["words"]
            source_id, object_id, output_id = video.object_id, output.object_id, output.id
            render_rate, storage_rate, units = service.budget(db, settings)
            reservation_id = job.reservation_id or UUID(job.checkpoint["expense_reservation"])
            prepaid = job.id if job.checkpoint.get("included_edit") else None
            attempt, fresh = money.admit_spend(
                db,
                owner,
                reservation_id,
                render_rate,
                units,
                f"render:{job.id}:{job.generation}",
                prepaid_render_job=prepaid,
            )
            if not fresh:
                raise ApiError(409, "render_admission_replay", "Render admission already consumed.")
            job.checkpoint = {**job.checkpoint, "render_attempt": str(attempt.id)}
            db.commit()
        heartbeat()
        # A crash after rename but before DB commit revalidates this file without encoding again.
        if storage.path(object_id).exists():
            metadata = engine.validate_output(
                storage.path(object_id),
                prefs,
                settings,
                time.monotonic() + settings.render_deadline_seconds,
                heartbeat,
            )
            metadata["framing"] = "recovered_verified_output"
        else:
            metadata = engine.render(
                storage.path(source_id), storage.path(token), prefs, words, settings, heartbeat
            )
        used = max(1, math.ceil(cpu() - started))
        with factory() as db:
            job = current(db, owner, job_id, token)
            reconcile(db, job, used)
            if job.state == "CANCEL_REQUESTED":
                media.terminate(db, job, "CANCELED")
                db.commit()
                return
            video = service.retained(db, owner, job.video_id)
            media.capacity(db, settings, storage)
            # Reserve retention expense before publishing; no simultaneous unresolved CPU hold.
            denominator = 1024**3 * 86400
            numerator = metadata["size_bytes"] * max(
                1, int((video.expires_at - utcnow()).total_seconds())
            )
            days_units = max(1, (numerator + denominator - 1) // denominator)
            retention, fresh = money.admit_spend(
                db,
                owner,
                reservation_id,
                storage_rate,
                days_units,
                "render-storage:" + str(output_id),
                prepaid_render_job=prepaid,
            )
            if not fresh:
                raise ApiError(
                    409, "render_admission_replay", "Storage admission already consumed."
                )
            money.record_spend(
                db,
                owner,
                retention.id,
                units=days_units,
                outcome="success",
                evidence="render-storage:" + str(output_id),
            )
            if storage.path(token).exists():
                storage.promote(token, object_id)
            output = media.required(db, RenderOutput, output_id)
            output.state, output.metadata_json = "COMPLETE", metadata
            obj = media.required(db, StorageObject, object_id)
            obj.materialized_bytes = obj.reserved_bytes = metadata["size_bytes"]
            db.flush()
            pending = db.scalar(
                select(RenderOutput.id).where(
                    RenderOutput.job_id == job.id, RenderOutput.state != "COMPLETE"
                )
            )
            job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "render_attempt"}
            job.lease_token, job.lease_until = None, None
            if pending:
                media.event(db, job, "QUEUED")
                job.generation += 1
                db.add(Outbox(job_id=job.id, generation=job.generation))
            else:
                if job.reservation_id:
                    reservation = db.get(CreditReservation, job.reservation_id)
                    quote = db.get(Quote, reservation.quote_id)
                    price = db.get(PlanPrice, quote.price_version_id)
                    # Pinned commercial rules: historical duration quotes are unchanged.
                    per_clip = price.rules.get("credits_per_minute") == 0
                    completed = db.scalar(
                        select(func.count())
                        .select_from(RenderOutput)
                        .where(RenderOutput.job_id == job.id, RenderOutput.state == "COMPLETE")
                    )
                    money.finish(
                        db,
                        owner,
                        job.reservation_id,
                        "render-settle:" + str(job.id),
                        success=True,
                        evidence=str(job.id),
                        settled_credits=completed * price.rules["credits_per_output"]
                        if per_clip
                        else None,
                    )
                source_obj = media.required(db, StorageObject, video.object_id)
                if job.kind == "PROCESS":
                    source_obj.reserved_bytes = source_obj.materialized_bytes
                media.event(db, job, "COMPLETED")
            db.commit()
    except Exception as exc:
        with factory() as db:
            try:
                job = current(db, owner, job_id, token)
            except ApiError:
                return  # Expired worker cannot write a receipt or finalize finances.
            handle_error(db, job, exc, units=max(1, math.ceil(cpu() - started)))
            db.commit()
    finally:
        storage.delete(token)
