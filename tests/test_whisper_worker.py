"""Real PostgreSQL worker recovery/accounting with fake inference and fake Gemini."""

import pytest
import test_ai
from sqlalchemy import select

from zoclip.ai import worker as ai
from zoclip.ai.models import AIRequest, Transcript
from zoclip.ai.providers import ProviderFailure
from zoclip.credits.models import ProviderUsage, SpendAttempt, SystemLimits

financial_database = test_ai.financial_database
media = test_ai.media
video_bytes = test_ai.video_bytes
processing = test_ai.processing


def configure(processing, monkeypatch, simulator):
    configured, video, job = processing
    factory, users, settings, storage = configured
    settings = settings.model_copy(update={"transcription_provider": "whisper"})
    monkeypatch.setattr(ai, "LocalWhisperProviders", lambda settings: simulator)
    return (factory, users, settings, storage), video, job


def test_whisper_pipeline_has_no_deepgram_charge_and_preserves_gemini(processing, monkeypatch):
    simulator = test_ai.Simulator()
    case = configure(processing, monkeypatch, simulator)
    assert test_ai.drive(case, monkeypatch, simulator) == ("SUGGESTIONS_READY", None)
    with case[0][0]() as db:
        requests = list(db.scalars(select(AIRequest)))
        assert {r.provider for r in requests} == {"whisper", "gemini"}
        local = next(r for r in requests if r.provider == "whisper")
        assert local.attempt_ids == [] and local.state == "RECORDED"
        assert len(list(db.scalars(select(SpendAttempt)))) == 2
        assert len(list(db.scalars(select(ProviderUsage)))) == 2
        assert db.scalars(select(Transcript)).one().model == "faster-whisper:small"


def test_whisper_failure_stops_before_gemini_and_releases_hold(processing, monkeypatch):
    simulator = test_ai.Simulator(dg=ProviderFailure("whisper_transcription_failed"))
    case = configure(processing, monkeypatch, simulator)
    assert test_ai.drive(case, monkeypatch, simulator)[0] == "FAILED"
    assert simulator.calls == ["deepgram"]  # Simulator label only; no HTTP transport exists.
    with case[0][0]() as db:
        assert not list(db.scalars(select(SpendAttempt)))
        assert not list(db.scalars(select(ProviderUsage)))
        test_ai.test_credits.assert_wallet(db, case[0][1]["alice"], 5, 0)


def test_closed_breaker_prevents_local_transcription(processing, monkeypatch):
    simulator = test_ai.Simulator()
    case = configure(processing, monkeypatch, simulator)
    with case[0][0]() as db:
        db.get(SystemLimits, 1).breaker = True
        db.commit()
    assert test_ai.drive(case, monkeypatch, simulator)[0] == "FAILED"
    assert simulator.calls == []


@pytest.mark.parametrize("boundary", ["receipt_before_db", "lost_response"])
def test_whisper_receipt_restart_never_dispatches_twice(processing, monkeypatch, boundary):
    simulator = test_ai.Simulator()
    case = configure(processing, monkeypatch, simulator)
    original = ai.checkpoint_response if boundary == "receipt_before_db" else ai.journal
    target = "checkpoint_response" if boundary == "receipt_before_db" else "journal"
    count = 0

    def crash(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise OSError("simulated worker loss")
        return original(*args, **kwargs)

    monkeypatch.setattr(ai, target, crash)
    state, _ = test_ai.drive(case, monkeypatch, simulator)
    assert state == ("SUGGESTIONS_READY" if boundary == "receipt_before_db" else "FAILED")
    assert simulator.calls.count("deepgram") == 1
    if boundary == "lost_response":
        assert "gemini" not in simulator.calls


class ChunkSimulator(test_ai.Simulator):
    def __init__(self, fail=False):
        super().__init__()
        self.windows = []
        self.fail = fail

    def transcribe_chunk(self, path, start, stop, progress, **bounds):
        progress()
        self.windows.append((start, stop))
        if self.fail and start == 29 and self.windows.count((start, stop)) == 1:
            raise OSError("simulated local worker interruption")
        from test_whisper_chunks import raw

        return {"status": 200, "body": raw([("Hello,", 1, 2)], stop - start)}


def chunk_case(processing, monkeypatch, simulator):
    import wave

    from zoclip.media.models import SourceVideo

    configured, video, jid = processing
    factory, users, settings, storage = configured
    settings = settings.model_copy(
        update={"transcription_provider": "whisper", "whisper_chunk_seconds": 30}
    )
    with factory() as db:
        source = db.get(SourceVideo, video)
        source.metadata_json = {
            **source.metadata_json,
            "duration_seconds": 65,
            "duration_ms": 65000,
        }
        db.commit()
    calls = []

    def extract(store, source, target, binary, duration, heartbeat):
        calls.append(1)
        with store.create(target) as handle, wave.open(handle, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            for _ in range(65):
                wav.writeframes(b"\0\0" * 16000)
        return "a" * 64, 65

    monkeypatch.setattr(ai.audio, "extract", extract)
    monkeypatch.setattr(ai, "LocalWhisperProviders", lambda settings: simulator)
    return ((factory, users, settings, storage), video, jid), calls


@pytest.mark.parametrize("failure", [False, True])
def test_chunks_requeue_under_existing_deadline_and_retry_only_unfinished_window(
    processing, monkeypatch, failure
):
    from zoclip.media.models import Job

    simulator = ChunkSimulator(failure)
    case, extractions = chunk_case(processing, monkeypatch, simulator)
    # Stop once the bounded local transcript is complete; Gemini is unchanged and
    # needs >=1s candidates in this fixture, not the sparse fake long transcript.
    factory, users, settings, storage = case[0]
    for _ in range(8):
        with factory() as db:
            job = db.get(Job, case[2])
            if job.checkpoint.get("transcript_id"):
                break
            assert job.state == "QUEUED"
            generation = job.generation
        test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    else:
        pytest.fail("Chunk progress did not converge")
    with factory() as db:
        job = db.get(Job, case[2])
        assert job.checkpoint["whisper_chunk_index"] == 3
        data = db.scalars(select(Transcript)).one().data
        assert [w["start"] for w in data["words"]] == [1, 30, 60]
        assert not storage.path(
            __import__("uuid").UUID(job.checkpoint["whisper_audio"]["id"])
        ).exists()
        assert all(r.state == "RECORDED" for r in db.scalars(select(AIRequest)))
        assert not list(db.scalars(select(SpendAttempt)))
        assert not list(db.scalars(select(ProviderUsage)))
    assert extractions == [1]
    assert simulator.windows.count((0, 31)) == 1
    assert simulator.windows.count((29, 61)) == (2 if failure else 1)


def test_batch_headroom_stops_claim_before_a_batch_can_straddle_the_rq_timeout(
    processing, monkeypatch
):
    from zoclip.media.models import Job

    simulator = ChunkSimulator()
    case, _extractions = chunk_case(processing, monkeypatch, simulator)
    factory, users, settings, storage = case[0]
    settings = settings.model_copy(
        update={"whisper_parallelism": 2, "whisper_batch_headroom_seconds": 0}
    )
    with factory() as db:
        generation = db.get(Job, case[2]).generation
    # Headroom 0: after the first batch the claim must stop and requeue
    # rather than start a batch that could cross the 660s RQ timeout.
    test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, case[2])
        assert job.state == "QUEUED"
        assert job.checkpoint["whisper_chunk_index"] == 2
        assert "transcript_id" not in job.checkpoint
    # A fresh claim always runs at least one batch, so progress converges.
    test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, case[2])
        assert job.checkpoint["whisper_chunk_index"] == 3
        assert job.checkpoint.get("transcript_id")


def test_chunk_receipt_before_db_crash_recovers_without_reinference(processing, monkeypatch):
    from zoclip.media.models import Job

    simulator = ChunkSimulator()
    case, extractions = chunk_case(processing, monkeypatch, simulator)
    original = ai.checkpoint_response
    calls = []

    def crash(*args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("simulated receipt-before-checkpoint crash")
        return original(*args, **kw)

    monkeypatch.setattr(ai, "checkpoint_response", crash)
    factory, users, settings, storage = case[0]
    for _ in range(8):
        with factory() as db:
            job = db.get(Job, case[2])
            if job.checkpoint.get("transcript_id"):
                break
            assert job.state == "QUEUED"
            generation = job.generation
        test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    else:
        pytest.fail("Receipt recovery did not finish")
    assert simulator.windows == [(0, 31), (29, 61), (59, 65)]
    assert extractions == [1]


def test_active_pcm_survives_orphan_sweep_and_cancel_releases_once(processing, monkeypatch):
    import os
    import time
    from uuid import UUID

    from zoclip.media.cleanup import cleanup
    from zoclip.media.models import Job

    simulator = ChunkSimulator()
    case, _ = chunk_case(processing, monkeypatch, simulator)
    factory, users, settings, storage = case[0]
    with factory() as db:
        generation = db.get(Job, case[2]).generation
    test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, case[2])
        audio_id = UUID(job.checkpoint["whisper_audio"]["id"])
    os.utime(storage.path(audio_id), (time.time() - 4000, time.time() - 4000))
    cleanup(factory, storage)
    assert storage.path(audio_id).exists()
    with factory() as db:
        test_ai.service.cancel_job(db, users["alice"], case[2])
        test_ai.service.cancel_job(db, users["alice"], case[2])
        db.commit()
        test_ai.test_credits.assert_wallet(db, users["alice"], 5, 0)
    cleanup(factory, storage)
    assert not storage.path(audio_id).exists()
    assert simulator.windows == [(0, 31)]


def test_local_worker_loss_resumes_after_last_committed_chunk(processing, monkeypatch):
    from datetime import timedelta

    from zoclip.core.db import utcnow
    from zoclip.media.models import Job

    simulator = ChunkSimulator()
    case, extractions = chunk_case(processing, monkeypatch, simulator)
    factory, users, settings, storage = case[0]
    original = simulator.transcribe_chunk
    lost = []

    def killed(path, start, stop, progress, **bounds):
        if start == 29 and not lost:
            lost.append(True)
            raise SystemExit("simulated killed work horse")
        return original(path, start, stop, progress, **bounds)

    simulator.transcribe_chunk = killed
    for claim in range(2):
        with factory() as db:
            generation = db.get(Job, case[2]).generation
        if claim == 1:
            with pytest.raises(SystemExit):
                test_ai.worker.run_job(case[2], generation, factory, settings, storage)
        else:
            test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, case[2])
        assert job.state == "RUNNING" and job.checkpoint["whisper_chunk_index"] == 1
        job.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert test_ai.worker.recover(factory, storage) == 1
    for _ in range(5):
        with factory() as db:
            job = db.get(Job, case[2])
            if job.checkpoint.get("transcript_id"):
                break
            assert job.state == "QUEUED"
            generation = job.generation
        test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    else:
        pytest.fail("Worker-loss recovery did not finish")
    assert simulator.windows == [(0, 31), (29, 61), (59, 65)]
    assert extractions == [1]
    with factory() as db:
        assert not list(db.scalars(select(SpendAttempt)))


def test_new_job_after_cancel_has_separate_partial_receipts(processing, monkeypatch):
    import test_media

    from zoclip.media.models import Job

    simulator = ChunkSimulator()
    case, extractions = chunk_case(processing, monkeypatch, simulator)
    factory, users, settings, storage = case[0]
    with factory() as db:
        generation = db.get(Job, case[2]).generation
    test_ai.worker.run_job(case[2], generation, factory, settings, storage)
    with factory() as db:
        test_ai.service.cancel_job(db, users["alice"], case[2])
        db.commit()
    new_job = test_media.process_job(case[0], case[1], key="after-cancel")
    for _ in range(5):
        with factory() as db:
            job = db.get(Job, new_job)
            if job.checkpoint.get("transcript_id"):
                break
            assert job.state == "QUEUED"
            generation = job.generation
        test_ai.worker.run_job(new_job, generation, factory, settings, storage)
    else:
        pytest.fail("New job after cancellation did not finish")
    with factory() as db:
        transcript = db.scalars(select(Transcript)).one()
        assert transcript.job_id == new_job
        requests = list(db.scalars(select(AIRequest)))
        assert len(requests) == 4
        assert sum(r.job_id == new_job for r in requests) == 3
    assert extractions == [1, 1]
