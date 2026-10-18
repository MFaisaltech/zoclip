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
