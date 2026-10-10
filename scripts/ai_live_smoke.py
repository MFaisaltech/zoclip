"""Manually run ONE already-admitted owned job. Never imported by the test gate.

No grants, rates, budgets or reservations are fabricated. Operator must create a
normal source/quote/job using an authorized account and reviewed configuration.
This command can spend real money; two explicit opt-ins are mandatory.
"""

import argparse
import os
import time
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from zoclip.ai.models import ClipSuggestion, Transcript
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.media.models import Job
from zoclip.media.storage import LocalStorage
from zoclip.media.worker import run_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=UUID, required=True)
    parser.add_argument("--owner", type=UUID, required=True)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid or os.environ.get("ZOCLIP_ALLOW_PAID_SMOKE") != "1":
        parser.error(
            "Paid calls disabled: both --allow-paid and ZOCLIP_ALLOW_PAID_SMOKE=1 required"
        )
    settings = Settings()  # type: ignore[call-arg]
    if settings.app_env != "development" or not settings.ai_configured:
        raise RuntimeError("Configured providers and an isolated development environment required")
    if os.environ.get("TEST_DATABASE_URL") or os.environ.get("ZOCLIP_PROVIDER_SIMULATOR"):
        raise RuntimeError("Live smoke cannot run inside automated test/simulator configuration")
    if any(
        key.get_secret_value().lower().startswith(("synthetic", "fictional", "test", "unused"))
        for key in (settings.deepgram_api_key, settings.gemini_api_key)
    ) or "fictional" in (settings.deepgram_model + settings.gemini_model):
        raise RuntimeError("Live smoke rejects known simulator credentials/models")
    engine = build_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    storage = LocalStorage(settings.media_root)
    try:
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            with factory() as db:
                job = db.get(Job, args.job)
                if not job or job.user_id != args.owner or job.kind != "PROCESS":
                    raise RuntimeError("Existing owned PROCESS job required")
                state, generation = job.state, job.generation
                if state == "SUGGESTIONS_READY":
                    from sqlalchemy import select

                    pinned = job.checkpoint.get("ai_config", {})
                    if any(
                        pinned.get(key) != getattr(settings, key)
                        for key in ("deepgram_model", "deepgram_version", "gemini_model")
                    ):
                        raise RuntimeError("Completed job does not match reviewed provider models")
                    transcript = db.get(Transcript, UUID(job.checkpoint["transcript_id"]))
                    suggestion = db.scalar(
                        select(ClipSuggestion).where(ClipSuggestion.job_id == job.id)
                    )
                    assert transcript and transcript.data["words"] and suggestion
                    print("PASS: word-timed transcript and validated suggestions; not rendered")
                    print("Review usefulness privately via owner-scoped API; credits remain held")
                    return
                if state not in {"QUEUED", "RUNNING"}:
                    raise RuntimeError("Smoke stopped: " + state + "/" + str(job.error_code))
            if state == "QUEUED":
                # Same fenced worker and expense admission as RQ; cache never bypassed.
                # Only the running maintenance/RQ scheduler handles delayed redelivery.
                if generation == 0:
                    run_job(args.job, generation, factory, settings, storage)
            time.sleep(1)
        raise RuntimeError("Bounded smoke deadline reached; inspect job before any retry")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
