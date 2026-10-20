"""Existing queue/worker fences with real PostgreSQL; no external providers."""

import pytest
import test_media
from sqlalchemy import func, select

from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction
from zoclip.media import worker
from zoclip.media.models import Job
from zoclip.ops.monitor import snapshot

financial_database = test_media.financial_database
media = test_media.media
video_bytes = test_media.video_bytes


def test_full_queue_rejection_rolls_back_credit_and_job_mutations(media, video_bytes):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    settings.media_pending_limit = 1  # Exercise the configured boundary, not a new runtime limit.
    with factory() as db:
        db.add(
            Job(
                user_id=users["bob"],
                video_id=video,
                kind="VALIDATE",
                operation_key="occupy-queue",
                request_hash="fixture",
                payload={},
            )
        )
        db.commit()
        before = (
            db.scalar(select(func.count()).select_from(CreditTransaction)),
            db.scalar(select(func.count()).select_from(Job)),
        )
    with pytest.raises(ApiError) as exc:
        test_media.process_job(media, video)
    assert exc.value.code == "queue_full" and exc.value.status == 429
    with factory() as db:
        wallet = money.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (5, 0)
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0
        assert before == (
            db.scalar(select(func.count()).select_from(CreditTransaction)),
            db.scalar(select(func.count()).select_from(Job)),
        )


def test_worker_claim_fences_one_ai_and_one_render_and_reports_backlog(media, video_bytes):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    with factory() as db:
        jobs = [
            Job(
                user_id=users[owner],
                video_id=video,
                kind="VALIDATE",
                operation_key=f"capacity-{i}",
                request_hash="fixture",
                payload={},
                checkpoint={"render_selection": True} if i == 2 else {},
            )
            for i, owner in enumerate(("alice", "bob", "bob"))
        ]
        db.add_all(jobs)
        db.commit()
        ids = [j.id for j in jobs]
        assert worker.claim(db, ids[0], 0)
        db.commit()
        assert worker.claim(db, ids[1], 0) is None
        db.commit()
        assert worker.claim(db, ids[2], 0)
        db.commit()
        report = snapshot(db, settings)["processing_capacity"]
        assert report["queued_jobs"] == 1 and report["running_jobs"] == 2
        assert report["oldest_queued_age_seconds"] >= 0
        assert report["oldest_running_heartbeat_age_seconds"] >= 0
        assert report["terminal_jobs_last_hour"] >= 1
