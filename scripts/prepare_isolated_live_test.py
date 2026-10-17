"""Prepare/inspect one operator-only entitlement. No approve or execute option."""

import argparse
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.ai.live_test_models import LiveTest, LiveTestCall
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.core.errors import ApiError
from zoclip.credits.service import fingerprint
from zoclip.media.storage import LocalStorage
from zoclip.ops import isolated_live_test as live


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--actor", type=UUID)
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    # Test-specific request settings; persistent public settings stay untouched.
    settings = settings.model_copy(
        update={
            "gemini_model": "gemini-3.1-flash-lite",
            "deepgram_model": "nova-3",
            "deepgram_version": "2025-07-31.0",
            "deepgram_language": "en",
            "deepgram_diarize": False,
            "deepgram_utterances": False,
            "deepgram_mip_opt_out": True,
            "ai_max_chunks": 1,
            "ai_chunk_bytes": 16000,
            "ai_max_candidates": 1,
            "ai_max_output_tokens": 2048,
            "ai_min_clip_seconds": 15,
            "ai_max_clip_seconds": 26,
            "render_max_bytes": 16 * 1024**2,
            "render_deadline_seconds": 240,
        }
    )
    storage = LocalStorage(settings.media_root)
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            live.closed(db, settings)
            if args.prepare:
                if not args.actor:
                    parser.error("--actor is required for audited preparation")
                row = live.prepare(db, settings, storage, args.actor)
                db.commit()
            else:
                row = db.get(LiveTest, 1)
            if row is None:
                live.stop("live_test_not_prepared")
            live.source(db, row, storage, settings)
            print(
                json.dumps(
                    {
                        "video_id": str(row.video_id),
                        "job_id": str(row.job_id),
                        "duration_ms": row.duration_ms,
                        "source_sha256": row.source_sha256,
                        "maximum_usd": str(row.cap_usd),
                        "committed_usd": str(row.committed_usd),
                        "state": row.state,
                        "approval_recorded": row.approval_hash is not None,
                        "policy_hash": fingerprint(row.policy),
                        "policy": row.policy,
                        "dispatch_count": db.scalar(select(func.count()).select_from(LiveTestCall)),
                        "credential_evidence_verified": row.credential_hashes is not None,
                        "public_ai_enabled": False,
                        "payments_enabled": False,
                    },
                    sort_keys=True,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STOP: " + (exc.code if isinstance(exc, ApiError) else type(exc).__name__))
        raise SystemExit(1) from None
