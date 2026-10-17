"""Single sponsored test, separate from public queues, credits and paid entitlements.

Preparation has no network side effects. Dispatch requires a separately recorded
explicit approval and verified account/credential evidence. Every slot is committed
before IO and is permanently spent even on rejection, timeout or process death.
"""

import hashlib
import json
import wave
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from zoclip.ai.acceptance import configuration
from zoclip.ai.live_test_models import LiveTest, LiveTestCall
from zoclip.ai.providers import HTTPProviders
from zoclip.ai.worker import usage
from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import SystemLimits
from zoclip.media.models import SourceVideo
from zoclip.media.probe import probe
from zoclip.media.storage import LocalStorage

VIDEO_ID = UUID("9cced2b6-cf08-410c-b653-318eef1dc5fe")
SOURCE_SHA256 = "4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80"
SOURCE_BYTES = 114549007
CAP = Decimal("0.10")
INPUT_TOKENS = 36000
OUTPUT_TOKENS = 2048


def stop(code: str) -> NoReturn:
    raise ApiError(503, code, "Isolated test safeguard refused execution.")


def closed(db: Session, settings: Settings) -> None:
    if (
        db.scalar(
            text(
                "SELECT current_setting('fsync') = 'on' AND "
                "current_setting('synchronous_commit') = 'on'"
            )
        )
        is not True
    ):
        stop("live_test_database_not_durable")
    system = db.get(SystemLimits, 1)
    if (
        settings.ai_enabled
        or settings.payment_provider != "disabled"
        or settings.enable_live_payments
        or settings.enable_trial_credits
        or system is None
        or not system.breaker
    ):
        stop("live_test_public_controls")


def policy(settings: Settings) -> dict:
    if (
        settings.gemini_model != "gemini-3.1-flash-lite"
        or settings.deepgram_model != "nova-3"
        or settings.deepgram_version != "2025-07-31.0"
        or settings.deepgram_language != "en"
        or settings.deepgram_diarize
        or settings.deepgram_utterances
        or not settings.deepgram_mip_opt_out
        or settings.ai_max_chunks != 1
        or settings.ai_max_candidates != 1
        or settings.ai_max_output_tokens != OUTPUT_TOKENS
        or settings.ai_chunk_bytes > 16000
    ):
        stop("live_test_configuration")
    # Explicit versioned published-rate ceilings. Applicable account terms must
    # be verified before approval. No free tier, cache, batch or retry discounts.
    rates = {"deepgram": "0.0043", "input": "0.00000025", "output": "0.0000015"}
    ceilings = {
        "deepgram": str(Decimal(rates["deepgram"])),
        "gemini": str(
            Decimal(rates["input"]) * INPUT_TOKENS + Decimal(rates["output"]) * OUTPUT_TOKENS
        ),
        # Reserve ALL remaining cap for bounded local extraction/render/storage.
        # This allocation is an operator ceiling, not a fabricated invoice rate.
        "render": str(
            CAP
            - Decimal(rates["deepgram"])
            - Decimal(rates["input"]) * INPUT_TOKENS
            - Decimal(rates["output"]) * OUTPUT_TOKENS
        ),
    }
    return {
        "version": 1,
        "configuration": configuration(settings),
        "rates": rates,
        "ceilings": ceilings,
        "input_tokens": INPUT_TOKENS,
        "output_tokens_including_thinking": OUTPUT_TOKENS,
        "deepgram_minutes": 1,
        "clips": 1,
        "paid_retries": 0,
        "render_deadline_seconds": settings.render_deadline_seconds,
        "render_max_bytes": settings.render_max_bytes,
        "retention_seconds": settings.media_retention_seconds,
        "min_clip_seconds": settings.ai_min_clip_seconds,
        "max_clip_seconds": settings.ai_max_clip_seconds,
    }


def source(db: Session, row: LiveTest, storage: LocalStorage, settings: Settings) -> Path:
    video = db.get(SourceVideo, row.video_id)
    user = db.get(User, row.user_id)
    if (
        not video
        or not user
        or user.status != "active"
        or not user.verified
        or video.user_id != row.user_id
        or video.state != "READY"
        or video.expires_at <= utcnow()
        or video.metadata_json.get("sha256") != row.source_sha256
        or video.metadata_json.get("duration_ms") != row.duration_ms
    ):
        stop("live_test_source_binding")
    path = storage.path(video.object_id)
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if path.stat().st_size != row.source_bytes or actual != row.source_sha256:
        stop("live_test_source_integrity")
    metadata = probe(path, settings.ffprobe_binary)
    if metadata["duration_ms"] != row.duration_ms or not 25000 <= row.duration_ms <= 27000:
        stop("live_test_source_duration")
    return path


def prepare(db: Session, settings: Settings, storage: LocalStorage, actor: UUID) -> LiveTest:
    closed(db, settings)
    money.staff(db, actor, "Prepare source-bound USD 0.10 isolated test; no paid execution")
    # Serialize creation with existing financial mutex, without opening its breaker.
    db.scalar(select(SystemLimits).where(SystemLimits.id == 1).with_for_update())
    old = db.get(LiveTest, 1)
    if old:
        if old.policy != policy(settings):
            stop("live_test_policy_changed")
        source(db, old, storage, settings)
        return old
    video = db.get(SourceVideo, VIDEO_ID)
    if not video:
        stop("live_test_video_missing")
    row = LiveTest(
        id=1,
        job_id=uuid4(),
        video_id=VIDEO_ID,
        user_id=video.user_id,
        actor_id=actor,
        source_sha256=SOURCE_SHA256,
        source_bytes=SOURCE_BYTES,
        duration_ms=video.metadata_json.get("duration_ms", 0),
        cap_usd=CAP,
        committed_usd=Decimal(0),
        policy=policy(settings),
        state="PREPARED",
    )
    source(db, row, storage, settings)
    if sum(map(Decimal, row.policy["ceilings"].values())) != CAP:
        stop("live_test_budget_invalid")
    db.add(row)
    db.flush()
    money.audit(db, actor, "ops.isolated_test_prepared", row.job_id)
    return row


def credential_hashes(settings: Settings) -> dict:
    values = {
        "deepgram": settings.deepgram_api_key.get_secret_value(),
        "gemini": settings.gemini_api_key.get_secret_value(),
    }
    if any(
        len(value) < 20 or value.lower().startswith(("synthetic", "placeholder", "change"))
        for value in values.values()
    ):
        stop("live_test_credentials_missing")
    return {name: hashlib.sha256(value.encode()).hexdigest() for name, value in values.items()}


def approve(db: Session, settings: Settings, actor: UUID, evidence: dict) -> None:
    """Trusted operator only, AFTER explicit user authorization. No HTTP route.

    Evidence must record console/account validation of the exact credential hashes,
    applicable rate ceilings and licensed source consent. Mere key presence is
    insufficient. This function must never manufacture that external evidence.
    """
    closed(db, settings)
    money.staff(db, actor, "Explicit owner authorization of one isolated live test")
    row = db.scalar(select(LiveTest).where(LiveTest.id == 1).with_for_update())
    if not row or row.state != "PREPARED" or row.approval_hash is not None:
        stop("live_test_approval_consumed")
    hashes = credential_hashes(settings)
    if (
        evidence.get("explicit_owner_authorization") is not True
        or evidence.get("job_id") != str(row.job_id)
        or evidence.get("video_id") != str(row.video_id)
        or evidence.get("source_sha256") != row.source_sha256
        or evidence.get("max_usd") != "0.10"
        or evidence.get("credential_hashes") != hashes
        or evidence.get("credentials_account_verified") is not True
        or evidence.get("applicable_rates_verified") != row.policy["rates"]
        or evidence.get("source_consent_verified") is not True
        or evidence.get("policy_hash") != money.fingerprint(row.policy)
        or not isinstance(evidence.get("verification_reference"), str)
        or not 10 <= len(evidence["verification_reference"]) <= 128
    ):
        stop("live_test_evidence_unverified")
    row.state, row.approval_hash = "APPROVED", money.fingerprint(evidence)
    row.approval_until = utcnow() + timedelta(hours=1)
    row.credential_hashes = hashes
    money.audit(db, actor, "ops.isolated_test_approved", row.job_id)


def admit(
    db: Session, settings: Settings, storage: LocalStorage, job_id: UUID, component: str
) -> UUID:
    closed(db, settings)
    row = db.scalar(
        select(LiveTest)
        .where(LiveTest.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not row
        or row.job_id != job_id
        or row.state != "APPROVED"
        or not row.approval_hash
        or not row.approval_until
        or row.approval_until <= utcnow()
        or row.policy != policy(settings)
        or row.cap_usd != CAP
        or row.credential_hashes != credential_hashes(settings)
    ):
        stop("live_test_entitlement_invalid")
    source(db, row, storage, settings)
    calls = list(db.scalars(select(LiveTestCall)))
    if component not in row.policy["ceilings"] or any(c.component == component for c in calls):
        stop("live_test_slot_consumed")
    required = {"deepgram": set(), "gemini": {"deepgram"}, "render": {"deepgram", "gemini"}}[
        component
    ]
    if {c.component for c in calls} != required or any(c.state != "RECORDED" for c in calls):
        stop("live_test_unverified_usage")
    total = sum((c.ceiling_usd for c in calls), Decimal(0))
    ceiling = Decimal(row.policy["ceilings"][component])
    if total != row.committed_usd or total + ceiling > CAP:
        stop("live_test_budget_exceeded")
    call = LiveTestCall(test_id=1, component=component, ceiling_usd=ceiling)
    db.add(call)
    db.flush()  # DB trigger charges the permanent hold and checks cap independently.
    return call.id


def provider_call(
    factory: sessionmaker,
    settings: Settings,
    storage: LocalStorage,
    job_id: UUID,
    provider: str,
    *,
    audio_path: Path | None = None,
    body: dict | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    # Validate the complete outgoing payload BEFORE consuming a durable slot.
    if provider == "deepgram":
        if audio_path is None:
            stop("live_test_audio_missing")
        with wave.open(str(audio_path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getframerate() != 16000
                or audio.getsampwidth() != 2
                or not 0 < audio.getnframes() <= 27 * 16000
            ):
                stop("live_test_audio_limit")
    elif provider == "gemini":
        from zoclip.ai.providers import gemini_body

        if (
            not body
            or set(body) != {"contents", "generationConfig"}
            or body.get("generationConfig") != gemini_body("", settings)["generationConfig"]
            or len(json.dumps(body, ensure_ascii=False).encode()) + 1024 > INPUT_TOKENS
        ):
            stop("live_test_input_limit")
        contents = body["contents"]
        if (
            not isinstance(contents, list)
            or len(contents) != 1
            or set(contents[0]) != {"role", "parts"}
            or contents[0]["role"] != "user"
            or len(contents[0]["parts"]) != 1
            or set(contents[0]["parts"][0]) != {"text"}
            or not isinstance(contents[0]["parts"][0]["text"], str)
        ):
            stop("live_test_input_limit")
    else:
        stop("live_test_provider_invalid")
    with factory() as db:
        request_id = admit(db, settings, storage, job_id, provider)
        db.commit()  # Sole permission for this process; never reconstructed after restart.
    try:
        adapter = HTTPProviders(settings, transport=transport)
        if provider == "deepgram":
            assert audio_path is not None
            result = adapter.transcribe(audio_path)
        else:
            assert body is not None
            result = adapter.analyze(body)
        quantities = usage(result, provider)
        valid = result["status"] == 200 and quantities is not None
        if valid and quantities is not None:
            maximum = [1] if provider == "deepgram" else [INPUT_TOKENS, OUTPUT_TOKENS]
            valid = all(
                type(u) is int and 0 < u <= m for u, m in zip(quantities, maximum, strict=True)
            )
        with factory() as db:
            row = db.scalar(select(LiveTest).where(LiveTest.id == 1).with_for_update())
            call = db.get(LiveTestCall, request_id)
            call.state = "RECORDED" if valid else "UNKNOWN"
            call.response = result
            if not valid:
                row.state = "STOPPED"
            db.commit()
        if not valid:
            stop("live_test_provider_usage_unverified")
        return result
    except BaseException:
        # Best effort only: a process kill still leaves HELD, permanently consumed.
        with factory() as db:
            row = db.scalar(select(LiveTest).where(LiveTest.id == 1).with_for_update())
            call = db.get(LiveTestCall, request_id)
            if call.state == "HELD":
                call.state = "UNKNOWN"
            if row.state != "COMPLETED":
                row.state = "STOPPED"
            db.commit()
        raise


def execute(factory: sessionmaker, settings: Settings, storage: LocalStorage, job_id: UUID) -> dict:
    """Explicit operator entry point only. Never invoked by an API, RQ or scheduler.

    No restart/retry mode: consumed provider/render slots make a repeated run stop.
    Returned output is a private operator artifact, never public customer access.
    """
    import time

    from zoclip.ai import audio, selection
    from zoclip.ai.providers import gemini_body
    from zoclip.ai.schemas import Moments
    from zoclip.media import service as media
    from zoclip.rendering import engine
    from zoclip.rendering.schemas import Preferences

    with factory() as db:
        closed(db, settings)
        row = db.get(LiveTest, 1)
        if not row or row.job_id != job_id or row.state != "APPROVED":
            stop("live_test_entitlement_invalid")
        video = db.get(SourceVideo, row.video_id)
        source_id = video.object_id
        seconds = (row.duration_ms + 999) // 1000
        source(db, row, storage, settings)
        media.capacity(db, settings, storage)
    audio_id, output_id = uuid4(), uuid4()
    try:
        audio.extract(storage, source_id, audio_id, settings.ffmpeg_binary, seconds, lambda: None)
        dg = provider_call(
            factory, settings, storage, job_id, "deepgram", audio_path=storage.path(audio_id)
        )
        transcript = selection.transcript(dg["body"], seconds)
        chunks = list(selection.chunks(transcript.words, settings))
        if len(chunks) != 1:
            stop("live_test_single_chunk_required")
        body = gemini_body(selection.prompt(chunks[0], settings, 1), settings)
        gm = provider_call(factory, settings, storage, job_id, "gemini", body=body)
        candidate = gm["body"]["candidates"][0]
        if candidate["finishReason"] != "STOP":
            stop("live_test_incomplete_output")
        raw = "".join(p["text"] for p in candidate["content"]["parts"] if not p.get("thought"))
        moments = Moments.model_validate_json(raw)
        chosen = selection.select_moments(moments.moments, transcript.words, seconds, settings, 1)
        if len(chosen) != 1:
            stop("live_test_single_clip_required")
        moment = chosen[0]
        prefs = Preferences(
            start_ms=round(moment.start_sec * 1000),
            end_ms=round(moment.end_sec * 1000),
            title=moment.title,
            hashtags=moment.hashtags,
            frame="center",
            captions=True,
        )
        with factory() as db:
            media.capacity(db, settings, storage, 2 * settings.render_max_bytes)
            request_id = admit(db, settings, storage, job_id, "render")
            db.commit()
        with storage.create(output_id):
            pass
        # Engine enforces deadline, bytes, constrained subprocesses and validates MP4.
        metadata = engine.render(
            storage.path(source_id),
            storage.path(output_id),
            prefs,
            [w.model_dump() for w in transcript.words],
            settings,
            lambda: None,
        )
        engine.validate_output(
            storage.path(output_id), prefs, settings, time.monotonic() + 25, lambda: None
        )
        result = {
            "object_id": str(output_id),
            "metadata": metadata,
            "expires_at": video.expires_at.isoformat(),
        }
        with factory() as db:
            row = db.scalar(select(LiveTest).where(LiveTest.id == 1).with_for_update())
            call = db.get(LiveTestCall, request_id)
            call.state, call.response = "RECORDED", result
            row.state = "COMPLETED"
            db.commit()
        return result
    except BaseException:
        storage.delete(output_id)
        with factory() as db:
            row = db.scalar(select(LiveTest).where(LiveTest.id == 1).with_for_update())
            if row and row.job_id == job_id and row.state != "COMPLETED":
                row.state = "STOPPED"
            db.commit()
        raise
    finally:
        storage.delete(audio_id)
