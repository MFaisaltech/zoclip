"""One bounded paid request per RQ claim; durable PG + fsynced response receipts.

Neither local caching nor a request ID promises exactly-once remote billing.
Missing receipts after admission retain UNKNOWN exposure and stop paid execution.
"""

import json
import math
import os
import time
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from zoclip.ai import audio, selection
from zoclip.ai.models import AIRequest, ClipSuggestion, Transcript
from zoclip.ai.providers import MAX_RESPONSE, HTTPProviders, Providers, gemini_body
from zoclip.ai.schemas import Moment, Moments, TranscriptData
from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, Quote
from zoclip.media import service
from zoclip.media.models import Job, Outbox, SourceVideo
from zoclip.media.storage import LocalStorage

CONFIG_KEYS = (
    "deepgram_model",
    "deepgram_version",
    "deepgram_language",
    "deepgram_diarize",
    "deepgram_utterances",
    "deepgram_mip_opt_out",
    "gemini_model",
    "ai_chunk_bytes",
    "ai_max_chunks",
    "ai_max_output_tokens",
    "ai_max_candidates",
    "ai_min_clip_seconds",
    "ai_max_clip_seconds",
)


def dg_options(settings: Settings) -> dict:
    return {k: getattr(settings, k) for k in CONFIG_KEYS if k.startswith("deepgram_")}


def deepgram_rate_label(settings: Settings) -> str:
    return "deepgram:" + money.fingerprint(dg_options(settings))


def checked(db: Session, owner: UUID, job_id: UUID, token: UUID) -> Job:
    money.lock_wallet(db, owner, active_required=False)
    job = service.owned(db, Job, owner, job_id, lock=True)
    if (
        job.lease_token != token
        or not job.lease_until
        or job.lease_until <= utcnow()
        or job.state not in {"RUNNING", "CANCEL_REQUESTED"}
    ):
        raise ApiError(409, "stale_worker", "Worker no longer owns this job.")
    video = service.owned(db, SourceVideo, owner, job.video_id)
    user = service.required(db, User, owner)
    if (
        job.state == "CANCEL_REQUESTED"
        or video.state != "READY"
        or video.expires_at <= utcnow()
        or user.status != "active"
        or not user.verified
    ):
        raise ApiError(409, "job_canceled", "Processing authorization was revoked.")
    reservation = service.owned(db, CreditReservation, owner, job.reservation_id)
    if reservation.job_id != job.id or reservation.state != "HELD":
        raise ApiError(409, "reservation_final", "Processing needs an owned active reservation.")
    return job


def stage(db: Session, job: Job, value: str) -> None:
    job.checkpoint = {**job.checkpoint, "ai_stage": value}
    job.heartbeat_at = utcnow()
    service.event(db, job, "RUNNING", value.lower())


def requeue(db: Session, job: Job, *, delay: float = 0) -> None:
    service.event(db, job, "QUEUED")
    job.generation += 1
    job.lease_token, job.lease_until = None, None
    db.add(
        Outbox(
            job_id=job.id,
            generation=job.generation,
            dispatch_until=utcnow() + timedelta(seconds=delay),
        )
    )


def journal(storage: LocalStorage, request_id: UUID, result: dict) -> None:
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_RESPONSE + 1024:
        raise ApiError(422, "provider_response_limit", "Provider response exceeded limits.")
    temp = uuid4()
    try:
        with storage.create(temp) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        storage.promote(temp, request_id)
    finally:
        storage.delete(temp)


def read_receipt(storage: LocalStorage, request_id: UUID) -> dict | None:
    try:
        with storage.open(request_id) as handle:
            raw = handle.read(MAX_RESPONSE + 1025)
            if len(raw) > MAX_RESPONSE + 1024:
                raise ValueError("receipt limit")
            result = json.loads(raw)
            if not isinstance(result, dict) or set(result) != {"status", "body"}:
                raise ValueError("receipt structure")
            return result
    except FileNotFoundError:
        return None


def checkpoint_response(factory: sessionmaker, owner: UUID, request_id: UUID, result: dict) -> None:
    with factory() as db:
        money.lock_wallet(db, owner, active_required=False)
        row = service.owned(db, AIRequest, owner, request_id, lock=True)
        if row.state in {"ADMITTED", "RESPONDED"}:
            row.response, row.response_hash = result, money.fingerprint(result)
            row.state = "RESPONDED"
        db.commit()


def usage(result: dict, provider: str) -> list[int] | None:
    try:
        body = result["body"]
        if result["status"] == 429:
            return [0] if provider == "deepgram" else [0, 0]
        if result["status"] != 200:
            return None
        if provider == "deepgram":
            duration = body["metadata"]["duration"]
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or not 0 < duration <= 7201
            ):
                return None
            return [math.ceil(duration / 60)]
        meta = body["usageMetadata"]
        values = [
            meta["promptTokenCount"],
            meta["candidatesTokenCount"],
            meta.get("thoughtsTokenCount", 0),
            meta["totalTokenCount"],
        ]
        if any(type(v) is not int or v < 0 or v > 10**9 for v in values):
            return None
        if values[3] < values[0] + values[1] + values[2]:
            return None
        # Count ALL residual tokens as output; no cached discounts or free thinking assumptions.
        return [values[0], values[3] - values[0]]
    except (KeyError, TypeError, ValueError):
        return None


def record_response(db: Session, row: AIRequest) -> dict | None:
    """Record evidence even after cancellation; never dispatch from reconciliation."""
    result = row.response
    status = result.get("status") if result else None
    quantities = usage(result, row.provider) if result else None
    for i, attempt in enumerate(row.attempt_ids):
        money.record_spend(
            db,
            row.user_id,
            UUID(attempt),
            units=None if quantities is None else quantities[i],
            outcome="unknown"
            if quantities is None
            else ("success" if status == 200 else "failure"),
            evidence=str(row.id),
        )
    row.state = "UNKNOWN" if quantities is None else ("REJECTED" if status == 429 else "RECORDED")
    return result if quantities is not None else None


def finalize_pending(db: Session, job: Job, storage: LocalStorage | None) -> None:
    for row in db.scalars(
        select(AIRequest).where(
            AIRequest.job_id == job.id,
            AIRequest.state.in_({"ADMITTED", "RESPONDED", "UNKNOWN"}),
        )
    ):
        if storage is not None:
            try:
                receipt = read_receipt(storage, row.id)
            except (OSError, ValueError):
                receipt = None
            if receipt:
                row.response, row.response_hash = receipt, money.fingerprint(receipt)
        record_response(db, row)


def reconcile_response(factory: sessionmaker, owner: UUID, request_id: UUID) -> dict:
    with factory() as db:
        money.lock_wallet(db, owner, active_required=False)
        row = service.owned(db, AIRequest, owner, request_id, lock=True)
        result = record_response(db, row)
        db.commit()
    if result is None:
        raise ApiError(503, "provider_outcome_unknown", "Provider expense requires reconciliation.")
    return result


def paid_request(
    factory: sessionmaker,
    settings: Settings,
    storage: LocalStorage,
    providers: Providers,
    owner: UUID,
    job_id: UUID,
    token: UUID,
    provider: str,
    cache_key: str,
    *,
    path: UUID | None = None,
    body: dict | None = None,
    duration: int,
) -> dict | None:
    with factory() as db:
        job = checked(db, owner, job_id, token)
        assert job.reservation_id is not None
        old = db.scalar(
            select(AIRequest)
            .where(
                AIRequest.user_id == owner,
                AIRequest.cache_key == cache_key,
            )
            .order_by(AIRequest.number.desc())
            .limit(1)
        )
        if old and old.state == "RECORDED":
            assert old.response is not None
            return {**old.response, "local_request_id": str(old.id)}
        if old and old.state in {"ADMITTED", "RESPONDED", "UNKNOWN"}:
            request_id, fresh = old.id, False
        else:
            number = old.number + 1 if old else 1
            if number > 3:
                raise ApiError(
                    503, "provider_retry_limit", "Provider rejection retry limit reached."
                )
            _, _, limits = money.locked_limits(db)
            rates = money.configured_rates(db, limits)
            recent = (
                db.scalar(
                    select(func.count())
                    .select_from(AIRequest)
                    .where(AIRequest.created_at >= utcnow() - timedelta(minutes=1))
                )
                or 0
            )
            if recent >= settings.ai_calls_per_minute:
                requeue(db, job, delay=60)
                db.commit()
                return None
            request_id = uuid4()
            key = "ai:" + str(request_id)
            if provider == "deepgram":
                if rates["deepgram"].model != deepgram_rate_label(settings):
                    raise ApiError(
                        503, "model_rate_mismatch", "Review rates for pinned Deepgram options."
                    )
                attempt, fresh = money.admit_spend(
                    db, owner, job.reservation_id, rates["deepgram"].id, (duration + 59) // 60, key
                )
                attempts = [attempt]
            else:
                if any(
                    rates[k].model != settings.gemini_model
                    for k in ("gemini_input", "gemini_output")
                ):
                    raise ApiError(
                        503, "model_rate_mismatch", "Review rates for pinned Gemini model."
                    )
                assert body is not None
                # UTF-8 byte upper bound + protocol/schema safety allowance, never chars/4.
                input_units = len(json.dumps(body, ensure_ascii=False).encode()) + 1024
                attempts, fresh = money.admit_gemini_spend(
                    db,
                    owner,
                    job.reservation_id,
                    rates["gemini_input"].id,
                    rates["gemini_output"].id,
                    input_units,
                    settings.ai_max_output_tokens,
                    key,
                )
            row = AIRequest(
                id=request_id,
                user_id=owner,
                video_id=job.video_id,
                job_id=job.id,
                provider=provider,
                model=settings.deepgram_model if provider == "deepgram" else settings.gemini_model,
                cache_key=cache_key,
                number=number,
                attempt_ids=[str(a.id) for a in attempts],
            )
            db.add(row)
        # Fresh committed admission is the ONLY authorization for a network side effect.
        db.commit()
    if fresh:
        # Recheck cancellation immediately before dispatch; if revoked, no request is sent.
        try:
            with factory() as db:
                checked(db, owner, job_id, token)
        except ApiError:
            with factory() as db:
                money.lock_wallet(db, owner, active_required=False)
                row = service.owned(db, AIRequest, owner, request_id, lock=True)
                for attempt in row.attempt_ids:
                    money.record_spend(
                        db,
                        owner,
                        UUID(attempt),
                        units=0,
                        outcome="failure",
                        evidence="not-dispatched:" + str(row.id),
                    )
                row.state = "REJECTED"
                db.commit()
            raise
        if provider == "deepgram":
            assert path is not None
            result = providers.transcribe(storage.path(path))
        else:
            assert body is not None
            result = providers.analyze(body)
        journal(storage, request_id, result)  # Fsync before separate DB checkpoint transaction.
        checkpoint_response(factory, owner, request_id, result)
    else:
        receipt = read_receipt(storage, request_id)
        if receipt:
            checkpoint_response(factory, owner, request_id, receipt)
    result = reconcile_response(factory, owner, request_id)
    if result["status"] == 429:
        from zoclip.media.worker import retry_delay

        with factory() as db:
            job = checked(db, owner, job_id, token)
            requeue(db, job, delay=retry_delay(min(job.attempts, 3)))
            db.commit()
        return None
    return {**result, "local_request_id": str(request_id)}


def run(
    job_id: UUID,
    owner: UUID,
    token: UUID,
    factory: sessionmaker,
    settings: Settings,
    storage: LocalStorage,
    providers: Providers | None = None,
) -> None:
    with factory() as db:
        job = checked(db, owner, job_id, token)
        if not settings.ai_configured:
            service.event(db, job, "WAITING_ENGINE", "processing_unavailable")
            job.checkpoint = {**job.checkpoint, "source_validated": True, "engine": "unavailable"}
            job.lease_token, job.lease_until = None, None
            db.commit()
            return
        pinned = job.checkpoint.get("ai_config") or {k: getattr(settings, k) for k in CONFIG_KEYS}
        job.checkpoint = {**job.checkpoint, "ai_config": pinned}
        settings = settings.model_copy(update=pinned)
        if settings.deepgram_language not in settings.ai_approved_languages:
            raise ApiError(503, "language_unapproved", "Job language is no longer approved.")
        video = service.owned(db, SourceVideo, owner, job.video_id)
        duration, source_id = video.metadata_json["duration_seconds"], video.object_id
        media_duration = video.metadata_json.get("duration_ms", duration * 1000) / 1000
        source_digest = video.metadata_json["sha256"]
        assert job.reservation_id is not None
        reservation = service.required(db, CreditReservation, job.reservation_id)
        quote = service.required(db, Quote, reservation.quote_id)
        count = min(settings.ai_max_candidates, quote.request["output_count"])
        transcript_key = money.fingerprint(
            [owner, video.id, source_digest, dg_options(settings), "pcm16k-v1"]
        )
        cached = db.scalar(
            select(Transcript).where(
                Transcript.user_id == owner, Transcript.cache_key == transcript_key
            )
        )
        cached_id = cached.id if cached else None
        stage(db, job, "ANALYZING" if cached else "EXTRACTING_AUDIO")
        db.commit()
    providers = providers or HTTPProviders(settings)
    if not cached_id:
        audio_id = uuid4()
        last_heartbeat = 0.0

        def heartbeat() -> None:
            nonlocal last_heartbeat
            if time.monotonic() - last_heartbeat < 3:
                return
            with factory() as db:
                job = checked(db, owner, job_id, token)
                # Same capacity envelope admitted in Phase 3 covers <=240MiB audio + receipts.
                service.mutex(db, owner)
                service.capacity(db, settings, storage)
                job.heartbeat_at = utcnow()
                db.commit()
            last_heartbeat = time.monotonic()

        try:
            audio_digest, audio_duration = audio.extract(
                storage, source_id, audio_id, settings.ffmpeg_binary, duration, heartbeat
            )
            with factory() as db:
                job = checked(db, owner, job_id, token)
                stage(db, job, "TRANSCRIBING")
                db.commit()
            response = paid_request(
                factory,
                settings,
                storage,
                providers,
                owner,
                job_id,
                token,
                "deepgram",
                transcript_key,
                path=audio_id,
                duration=duration,
            )
            if response is None:
                return
            data = selection.transcript(response["body"], min(media_duration, audio_duration))
            with factory() as db:
                job = checked(db, owner, job_id, token)
                cached = Transcript(
                    user_id=owner,
                    video_id=job.video_id,
                    job_id=job.id,
                    request_id=UUID(response["local_request_id"]),
                    cache_key=transcript_key,
                    model=settings.deepgram_model + "@" + settings.deepgram_version,
                    language=settings.deepgram_language,
                    audio_sha256=audio_digest,
                    data=data.model_dump(mode="json"),
                )
                db.add(cached)
                db.flush()
                job.checkpoint = {**job.checkpoint, "transcript_id": str(cached.id)}
                if not data.words:
                    service.terminate(db, job, "FAILED", "no_speech")
                else:
                    requeue(db, job)
                db.commit()
            return
        finally:
            storage.delete(audio_id)
    with factory() as db:
        cached = service.owned(db, Transcript, owner, cached_id)
        data = TranscriptData.model_validate(cached.data)
        job = checked(db, owner, job_id, token)
        job.checkpoint = {**job.checkpoint, "transcript_id": str(cached.id)}
        index = job.checkpoint.get("analysis_chunk", 0)
        all_chunks = list(selection.chunks(data.words, settings))
        collected = [Moment.model_validate(m) for m in job.checkpoint.get("candidates", [])]
        db.commit()
    if index < len(all_chunks):
        words = all_chunks[index]
        text = selection.prompt(words, settings, count)
        body = gemini_body(text, settings)
        key = money.fingerprint(
            [
                owner,
                transcript_key,
                audio_digest if not cached_id else cached.audio_sha256,
                settings.gemini_model,
                selection.PROMPT_VERSION,
                body,
            ]
        )
        response = paid_request(
            factory,
            settings,
            storage,
            providers,
            owner,
            job_id,
            token,
            "gemini",
            key,
            body=body,
            duration=duration,
        )
        if response is None:
            return
        try:
            result = response["body"]
            candidate = result["candidates"][0]
            if candidate["finishReason"] != "STOP":
                raise ValueError("incomplete candidate")
            raw = "".join(p["text"] for p in candidate["content"]["parts"] if not p.get("thought"))
            parsed = Moments.model_validate_json(raw)
            collected += selection.select_moments(parsed.moments, words, duration, settings, count)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ApiError(
                422, "invalid_suggestions", "Provider suggestions failed validation."
            ) from exc
    with factory() as db:
        job = checked(db, owner, job_id, token)
        if index + 1 < len(all_chunks):
            job.checkpoint = {
                **job.checkpoint,
                "analysis_chunk": index + 1,
                "candidates": [m.model_dump() for m in collected],
            }
            requeue(db, job)
        else:
            final = (
                selection.select_moments(collected, data.words, duration, settings, count)
                if data.words
                else []
            )
            if not final:
                service.terminate(db, job, "FAILED", "no_suggestions")
            else:
                for rank, moment in enumerate(final, 1):
                    db.add(
                        ClipSuggestion(
                            user_id=owner,
                            video_id=job.video_id,
                            job_id=job.id,
                            transcript_id=cached_id,
                            rank=rank,
                            data=moment.model_dump(),
                        )
                    )
                service.event(db, job, "SUGGESTIONS_READY")
                job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "candidates"}
                job.lease_token, job.lease_until = None, None
        db.commit()


def resume_waiting(factory: sessionmaker, settings: Settings) -> int:
    if not settings.ai_configured:
        return 0
    with factory() as db:
        ids = list(
            db.scalars(
                select(Job.id)
                .where(Job.kind == "PROCESS", Job.state == "WAITING_ENGINE")
                .limit(100)
            )
        )
    for job_id in ids:
        with factory() as db:
            initial = service.required(db, Job, job_id)
            service.mutex(db, initial.user_id, cleanup=True)
            job = service.owned(db, Job, initial.user_id, job_id, lock=True)
            if job.state == "WAITING_ENGINE":
                requeue(db, job)
                db.commit()
    return len(ids)


def handle_error(
    db: Session,
    job: Job,
    storage: LocalStorage | None,
    exc: Exception,
    *,
    recovering: bool = False,
) -> None:
    """Recover receipts with the same logical keys; unknown side effects stop safely."""
    failures = job.checkpoint.get("ai_failures", 0) + 1
    job.checkpoint = {**job.checkpoint, "ai_failures": failures}
    # A fixed-lease recovery can enqueue once; next claim loads its fsynced receipt.
    pending = list(
        db.scalars(
            select(AIRequest).where(
                AIRequest.job_id == job.id, AIRequest.state.in_({"ADMITTED", "RESPONDED"})
            )
        )
    )
    recoverable = recovering or any(
        r.response is not None or (storage is not None and storage.path(r.id).is_file())
        for r in pending
    )
    if failures < 3 and (
        recoverable or (not pending and isinstance(exc, (OSError, TimeoutError, SQLAlchemyError)))
    ):
        from zoclip.media.worker import retry_delay

        requeue(db, job, delay=retry_delay(failures))
        return
    finalize_pending(db, job, storage)
    code = (
        exc.code
        if isinstance(exc, ApiError)
        else ("provider_outcome_unknown" if pending else "ai_processing_failed")
    )
    service.terminate(db, job, "FAILED", code)
