"""Native Windows single-job acceptance driver. No queue/scheduler or implicit retry.

Persisted AI_ENABLED must stay false. Only the explicitly approved `ai` phase
constructs an enabled in-process Settings object; no environment/file is changed.
This command never seeds accounts, credits, plans, rates, budgets or payments.
"""

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from zoclip.ai import acceptance
from zoclip.ai import worker as ai
from zoclip.ai.models import AIRequest
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, Quote
from zoclip.media import service, worker
from zoclip.media.models import Job, SourceVideo, UploadSession
from zoclip.media.storage import LocalStorage
from zoclip.rendering.models import RenderOutput

ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "var/live-ai-readiness/acceptance-binding.json"
SAMPLE_HASH = "281841b42e88e04b3eaf4f361111550e4517e477c30f069e754bb5ee884bc3d0"
ATTESTATION = Path("F:/ZoClip-LiveAI/source-attestation.json")


def exclusive_record(path: Path, value: dict) -> None:
    """A partial/empty file is also consumed. Never truncate, remove or reset it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def isolated(settings: Settings) -> None:
    url = make_url(settings.database_url.get_secret_value())
    if (
        settings.app_env != "development"
        or settings.ai_enabled
        or (url.host, url.port, url.database) != ("127.0.0.1", 55439, "zoclip_live_readiness")
        or Path(settings.media_root).resolve() != Path("F:/ZoClip-LiveAI/media").resolve()
        or any(os.environ.get(k) for k in ("TEST_DATABASE_URL", "ZOCLIP_PROVIDER_SIMULATOR"))
    ):
        raise ValueError("Only the disabled isolated readiness environment is allowed")


def models_ready(settings: Settings) -> None:
    if (
        settings.gemini_model != "gemini-3.1-flash-lite"
        or settings.deepgram_model != "nova-3"
        or not settings.deepgram_version
        or settings.deepgram_version.lower() in {"latest", "beta"}
        or settings.deepgram_language != "en"
        or settings.deepgram_diarize
        or settings.deepgram_utterances
        or not settings.deepgram_mip_opt_out
        or settings.ai_max_chunks != 1
        or settings.ai_max_candidates != 1
        or settings.ai_chunk_bytes > 16000
        or settings.ai_max_output_tokens > 2048
    ):
        raise ValueError("Reviewed models/version and one-chunk short-test configuration required")


def require_approval() -> None:
    path = ATTESTATION
    continuation = os.environ.get("ZOCLIP_ACCEPTANCE_CONTINUATION")
    if continuation:
        from zoclip.ops.acceptance_continuation import ORIGINAL, phase_attestation

        if continuation != str(ORIGINAL):
            raise ValueError("Unknown continuation")
        path = phase_attestation(Settings(), ROOT)  # type: ignore[call-arg]
    approval = json.loads(path.read_text(encoding="utf-8"))
    if approval.get("live_processing_approved") is not True:
        raise ValueError("Recorded explicit live-test approval is required")


def selected(db: Session, owner: UUID, job_id: UUID) -> tuple[Job, SourceVideo]:
    job = service.owned(db, Job, owner, job_id, lock=True)
    video = service.owned(db, SourceVideo, owner, job.video_id)
    others = db.scalar(
        select(func.count()).select_from(Job).where(Job.id != job_id, Job.state.in_(service.ACTIVE))
    )
    if others:
        raise ValueError("Other active work exists; stop without dispatching it")
    return job, video


def source_ready(job: Job, video: SourceVideo) -> None:
    if (
        job.kind != "PROCESS"
        or video.state != "READY"
        or video.metadata_json.get("sha256") != SAMPLE_HASH
        or not 25 <= video.metadata_json.get("duration_seconds", 0) <= 30
    ):
        raise ValueError("Only the verified short sample PROCESS job is allowed")


def bind(factory: sessionmaker, settings: Settings, owner: UUID, job_id: UUID) -> None:
    models_ready(settings)
    with factory() as db:
        money.lock_wallet(db, owner)
        job, video = selected(db, owner, job_id)
        source_ready(job, video)
        if (
            job.state != "QUEUED"
            or acceptance.MARKER in job.checkpoint
            or db.scalar(select(func.count()).select_from(AIRequest))
        ):
            raise ValueError("Binding requires a fresh queued job and no provider history")
        if job.reservation_id is None:
            raise ValueError("An existing credit reservation is required")
        reservation = service.required(db, CreditReservation, job.reservation_id)
        quote = service.required(db, Quote, reservation.quote_id)
        if quote.request["output_count"] != 1 or quote.request.get("edit_count", 0) != 0:
            raise ValueError("Exactly one output and no re-exports required")
        binding = {
            "version": 1,
            "owner": str(owner),
            "job": str(job_id),
            "video": str(video.id),
            "source_sha256": SAMPLE_HASH,
            "configuration": acceptance.configuration(settings),
            "dispatches": {},
        }
        # A failed DB commit leaves this file consumed, requiring manual review.
        exclusive_record(BINDING, binding)
        job.checkpoint = {**job.checkpoint, acceptance.MARKER: binding}
        db.commit()
    print("Bound one acceptance job; no provider call or AI enablement.")


def advance_ai(
    factory: sessionmaker, settings: Settings, owner: UUID, job_id: UUID, storage: LocalStorage
) -> None:
    """Two checkpoint advances; any rejection/error stops without a retry."""
    for step in ("deepgram", "gemini"):
        with factory() as db:
            job, _ = selected(db, owner, job_id)
            if step == "gemini":
                dispatches = job.checkpoint[acceptance.MARKER]["dispatches"]
                receipt = db.scalar(
                    select(AIRequest).where(
                        AIRequest.job_id == job_id, AIRequest.provider == "deepgram"
                    )
                )
                if (
                    job.state != "QUEUED"
                    or not job.checkpoint.get("transcript_id")
                    or set(dispatches) != {"deepgram"}
                    or not receipt
                    or receipt.state != "RECORDED"
                    or not receipt.response
                    or receipt.response.get("status") != 200
                ):
                    raise ValueError("No successful transcription checkpoint; stop")
            claim = worker.claim(db, job_id, job.generation)
            db.commit()
        if not claim:
            raise ValueError("Claim refused; phase remains consumed")
        token, _ = claim
        try:
            ai.run(job_id, owner, token, factory, settings, storage)
        except Exception as error:
            with factory() as db:
                job = ai.checked(db, owner, job_id, token)
                ai.finalize_pending(db, job, storage)
                service.terminate(db, job, "FAILED", getattr(error, "code", "acceptance_stopped"))
                db.commit()
            raise ValueError("Acceptance stopped; inspect durable receipts, never retry") from None


def execute(
    factory: sessionmaker, settings: Settings, owner: UUID, job_id: UUID, phase: str
) -> None:
    storage = LocalStorage(settings.media_root)
    with factory() as db:
        money.lock_wallet(db, owner)
        job, video = selected(db, owner, job_id)
        if job.state != "QUEUED":
            raise ValueError("Only a fresh queued phase can execute; no automatic recovery")
        generation = job.generation
        if phase == "validate":
            upload = db.scalar(select(UploadSession).where(UploadSession.video_id == video.id))
            if job.kind != "VALIDATE" or not upload or upload.sha256 != SAMPLE_HASH:
                raise ValueError("Only the sample upload validation job is permitted")
        else:
            source_ready(job, video)
            binding = json.loads(BINDING.read_text(encoding="utf-8"))
            current = job.checkpoint.get(acceptance.MARKER, {})
            if (
                binding.get("job") != str(job_id)
                or current.get("job") != str(job_id)
                or current.get("configuration") != acceptance.configuration(settings)
            ):
                raise ValueError("Durable acceptance binding does not match")
            if phase == "ai":
                models_ready(settings)
                if job.checkpoint.get("render_selection") or current.get("dispatches"):
                    raise ValueError("AI phase is already consumed or no longer fresh")
                if os.environ.get("ZOCLIP_ALLOW_PAID_ACCEPTANCE") != "1":
                    raise ValueError("Separate paid opt-in required")
                require_approval()
                # Validated only after explicit paid opt-ins. The .env stays disabled.
                settings = Settings(  # type: ignore[call-arg]
                    _env_file=None, **{**settings.model_dump(), "ai_enabled": True}
                )
                _, _, limits = money.locked_limits(db)
                if (
                    any(
                        getattr(limits, name) > Decimal("0.05")
                        for name in (
                            "per_job_usd",
                            "user_daily_usd",
                            "user_monthly_usd",
                            "global_daily_usd",
                            "global_monthly_usd",
                        )
                    )
                    or limits.max_open_reservations != 1
                    or limits.max_attempts_per_job != 5
                ):
                    raise ValueError("Reviewed one-job USD 0.05 policy required")
                money.configured_rates(db, limits)
            elif (
                not job.checkpoint.get("render_selection")
                or db.scalar(
                    select(func.count())
                    .select_from(RenderOutput)
                    .where(RenderOutput.job_id == job_id)
                )
                != 1
            ):
                raise ValueError("Exactly one approved render is required")
        db.rollback()
    # Never reset this phase marker after failure, crash, timeout or restart.
    exclusive_record(
        BINDING.with_name(f"acceptance-{phase}-entered.json"),
        {
            "owner": str(owner),
            "job": str(job_id),
            "phase": phase,
        },
    )
    if phase == "ai":
        advance_ai(factory, settings, owner, job_id, storage)
    else:
        worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        job = service.owned(db, Job, owner, job_id)
        expected = "SUGGESTIONS_READY" if phase == "ai" else "COMPLETED"
        if job.state != expected:
            raise ValueError("Phase did not complete; stop, do not dispatch again")
        print(f"PASS: {phase} reached {expected}; no background worker started.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["inspect", "bind", "validate", "ai", "render"], default="inspect"
    )
    parser.add_argument("--owner", type=UUID)
    parser.add_argument("--job", type=UUID)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if args.phase == "ai" and not args.allow_paid:
        parser.error("Live AI requires --allow-paid plus the separate environment opt-in")
    settings = Settings()  # type: ignore[call-arg]
    isolated(settings)
    engine = build_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        if args.phase == "inspect":
            with engine.connect() as connection:
                from sqlalchemy import text

                connection.execute(text("SET TRANSACTION READ ONLY"))
                limits = connection.execute(
                    text("SELECT breaker, policy_id IS NOT NULL FROM system_limits")
                ).all()
                print(
                    json.dumps(
                        {
                            "ai_enabled": False,
                            "breaker_policy_present": [list(r) for r in limits],
                            "binding_exists": BINDING.exists(),
                            "sample_hash": SAMPLE_HASH,
                        }
                    )
                )
        elif not args.owner or not args.job:
            parser.error("A specific owner and job are required")
        elif args.phase == "bind":
            bind(factory, settings, args.owner, args.job)
        else:
            execute(factory, settings, args.owner, args.job, args.phase)
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No exception payload/connection URL/provider response can leak to logs.
        print("STOP: " + (exc.code if isinstance(exc, ApiError) else type(exc).__name__))
        raise SystemExit(1) from None
