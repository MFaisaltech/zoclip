"""Real PostgreSQL, actual FFmpeg, simulated paid providers only."""

import copy
import json
import os
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
import test_credits
import test_media
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError

from alembic import command
from zoclip.ai import selection
from zoclip.ai import worker as ai
from zoclip.ai.models import AIRequest, ClipSuggestion, Transcript
from zoclip.ai.providers import HTTPProviders, ProviderFailure, gemini_body
from zoclip.ai.schemas import Moment, Moments, Word
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction, ProviderUsage, SpendAttempt
from zoclip.credits.schemas import PolicyInput, RateInput
from zoclip.media import service, worker
from zoclip.media.cleanup import cleanup
from zoclip.media.models import Job, JobEvent, SourceVideo

financial_database = test_credits.concurrent_db
media = test_media.media
video_bytes = test_media.video_bytes


def dg_payload():
    return {
        "metadata": {"duration": 2.5, "request_id": "synthetic-local"},
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "confidence": 0.9,
                            "words": [
                                {
                                    "word": w,
                                    "start": i * 0.5,
                                    "end": (i + 1) * 0.5,
                                    "confidence": 0.9,
                                    "speaker": i % 2,
                                }
                                for i, w in enumerate(
                                    ["Useful", "ideas", "help", "people", "learn."]
                                )
                            ],
                        }
                    ]
                }
            ]
        },
    }


def moment(**updates):
    return {
        "start_sec": 0,
        "end_sec": 2.5,
        "title": "Useful ideas",
        "hook": "Learn together",
        "reason": "A coherent insight",
        "score": 85,
        "keywords": ["learning"],
        "hashtags": ["#learning"],
        **updates,
    }


def gemini_payload(moments=None):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {"moments": [moment()] if moments is None else moments}
                            )
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
            "thoughtsTokenCount": 0,
            "totalTokenCount": 150,
        },
    }


class Simulator:
    def __init__(self, dg=None, gemini=None):
        self.dg = dg if dg is not None else dg_payload()
        self.gemini = gemini if gemini is not None else gemini_payload()
        self.calls = []

    def transcribe(self, path):
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 16000 and audio.getnchannels() == 1
            assert audio.getnframes() > 0
        self.calls.append("deepgram")
        if isinstance(self.dg, BaseException):
            raise self.dg
        return {"status": 200, "body": copy.deepcopy(self.dg)}

    def analyze(self, body):
        assert "video" not in body and body["generationConfig"]["candidateCount"] == 1
        self.calls.append("gemini")
        if isinstance(self.gemini, BaseException):
            raise self.gemini
        return {"status": 200, "body": copy.deepcopy(self.gemini)}


def configure(factory, users, settings):
    settings = settings.model_copy(
        update={
            "transcription_provider": "deepgram",  # This simulator tests paid Deepgram accounting.
            "analysis_provider": "gemini",  # Explicit mocked-provider accounting.
            "ai_enabled": True,
            "deepgram_api_key": "unused",
            "gemini_api_key": "unused",
            "deepgram_model": "fictional-test",
            "deepgram_version": "fixture-v1",
            "gemini_model": "fictional-test",
            "ai_min_clip_seconds": 1,
            "ai_max_output_tokens": 128,
            "ai_calls_per_minute": 60,
            "ffmpeg_binary": os.environ.get("FFMPEG_BINARY", "ffmpeg"),
        }
    )
    # Validate SecretStr rather than an unsafe model_copy coercion.
    settings = Settings(_env_file=None, **settings.model_dump())
    with factory() as db:
        rate = money.configure_rate(
            db,
            RateInput(
                component="deepgram",
                unit="minute",
                model=ai.deepgram_rate_label(settings),
                unit_usd=Decimal("0.01"),
                max_units=100000,
                reason="Fictional simulator option pricing",
            ),
            "ai-rate",
            users["admin"],
        )
        limits = users["limits"].model_copy(
            update={
                "rate_ids": [
                    rate.id if r == users["rates"]["deepgram"] else r
                    for r in users["limits"].rate_ids
                ],
                "max_output_tokens": 128,
            }
        )
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Fictional simulator budgets only"),
            "ai-policy",
            users["admin"],
        )
        db.commit()
    users["ai_limits"] = limits
    return settings


@pytest.fixture
def processing(media, video_bytes):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    settings = configure(factory, users, settings)
    configured = factory, users, settings, storage
    job = test_media.process_job(configured, video)
    return configured, video, job


def drive(processing, monkeypatch, simulator, *, max_steps=20):
    media, _, job_id = processing
    factory, users, settings, storage = media
    monkeypatch.setattr(ai, "HTTPProviders", lambda settings: simulator)
    for _ in range(max_steps):
        with factory() as db:
            job = db.get(Job, job_id)
            if job.state != "QUEUED":
                return job.state, job.error_code
            generation = job.generation
        worker.run_job(job_id, generation, factory, settings, storage)
    pytest.fail("Pipeline failed to reach a bounded outcome")


def test_pipeline_real_audio_durable_costs_no_settlement(processing, monkeypatch):
    simulator = Simulator()
    assert drive(processing, monkeypatch, simulator) == ("SUGGESTIONS_READY", None)
    (factory, users, settings, storage), video, job = processing
    with factory() as db:
        row = db.get(Job, job)
        assert row.progress_percent is None and row.stage == "SUGGESTIONS_READY"
        assert db.get(CreditReservation, row.reservation_id).state == "HELD"
        test_credits.assert_wallet(db, users["alice"], 4, 1)
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == 3
        assert db.scalar(select(func.count()).select_from(ClipSuggestion)) == 1
        assert db.scalar(select(func.count()).select_from(Transcript)) == 1
        states = list(db.scalars(select(JobEvent.code).where(JobEvent.job_id == job)))
        assert {"extracting_audio", "transcribing", "analyzing"}.issubset(states)
    worker.run_job(job, 0, factory, settings, storage)
    assert simulator.calls == ["deepgram", "gemini"]
    with factory() as db:
        service.cancel_job(db, users["alice"], job)
        service.cancel_job(db, users["alice"], job)
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 5, 0)
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 0
        )
    # Same unchanged source + identical options reuses both providers across jobs.
    second = test_media.process_job(processing[0], video, "second")
    assert drive((processing[0], video, second), monkeypatch, simulator)[0] == "SUGGESTIONS_READY"
    assert simulator.calls == ["deepgram", "gemini"]


@pytest.mark.parametrize(
    "payload,code",
    [
        ({}, "provider_outcome_unknown"),
        ({"metadata": {"duration": 2.5}, "results": {}}, "invalid_transcription"),
        (ProviderFailure("timeout"), "provider_outcome_unknown"),
    ],
)
def test_transcription_failure_releases_but_retains_cost_exposure(
    processing, monkeypatch, payload, code
):
    assert drive(processing, monkeypatch, Simulator(dg=payload)) == ("FAILED", code)
    with processing[0][0]() as db:
        test_credits.assert_wallet(db, processing[0][1]["alice"], 5, 0)
        assert db.scalar(select(func.count()).select_from(SpendAttempt)) == 1
        row = db.scalar(select(SpendAttempt))
        assert row.state == ("UNKNOWN" if code == "provider_outcome_unknown" else "RECORDED")


@pytest.mark.parametrize(
    "mode", ["silence", "bad_timestamp", "nan", "bad_confidence", "giant_word"]
)
def test_transcript_validation_failure_modes(processing, monkeypatch, mode):
    payload = dg_payload()
    words = payload["results"]["channels"][0]["alternatives"][0]["words"]
    if mode == "silence":
        words.clear()
    elif mode == "bad_timestamp":
        words[-1]["end"] = 20
    elif mode == "nan":
        words[0]["start"] = float("nan")
    elif mode == "bad_confidence":
        words[0]["confidence"] = -1
    else:
        words[0]["word"] = "x" * 201
    result = drive(processing, monkeypatch, Simulator(dg=payload))
    assert result[0] == "FAILED"
    assert result[1] in {"invalid_transcription", "no_speech", "provider_outcome_unknown"}


@pytest.mark.parametrize(
    "mode", ["invalid_json", "missing_usage", "empty", "too_many", "timeout", "truncated"]
)
def test_analysis_failure_preserves_transcript_and_sunk_cost(processing, monkeypatch, mode):
    payload = gemini_payload()
    if mode == "invalid_json":
        payload["candidates"][0]["content"]["parts"][0]["text"] = "invalid"
    elif mode == "missing_usage":
        payload.pop("usageMetadata")
    elif mode == "empty":
        payload = gemini_payload([])
    elif mode == "too_many":
        payload = gemini_payload([moment()] * 21)
    elif mode == "timeout":
        payload = ProviderFailure("timeout")
    else:
        payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
    simulator = Simulator(gemini=payload)
    assert drive(processing, monkeypatch, simulator)[0] == "FAILED"
    with processing[0][0]() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 1
        assert db.scalar(select(func.count()).select_from(SpendAttempt)) == 3
        test_credits.assert_wallet(db, processing[0][1]["alice"], 5, 0)
    assert simulator.calls == ["deepgram", "gemini"]


def test_alignment_overlap_clamping_and_ranking():
    words = selection.transcript(dg_payload(), 3).words
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://local/local", ai_min_clip_seconds=1
    )
    candidates = [
        Moment(**moment(start_sec=-1, end_sec=99, score=90)),
        Moment(**moment(start_sec=0.1, end_sec=2.4)),
        Moment(**moment(start_sec=90, end_sec=100)),
        Moment(**moment(start_sec=2, end_sec=1)),
    ]
    result = selection.select_moments(candidates, words, 3, settings, 10)
    assert len(result) == 1 and (result[0].start_sec, result[0].end_sec) == (0, 2.5)
    assert result[0].score == 90
    with pytest.raises(ValidationError):
        Moments(moments=[moment(score=float("inf"))])


def test_unicode_chunking_bounded_and_absolute_timestamps():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://local/local",
        ai_chunk_bytes=1000,
        ai_max_chunks=64,
    )
    words = [
        Word(word="پاکستان", punctuated_word="پاکستان", start=i, end=i + 0.5, confidence=0.8)
        for i in range(100)
    ]
    groups = list(selection.chunks(words, settings))
    assert len(groups) > 1
    assert groups[0][0].start == 0 and groups[-1][-1].end == 99.5
    assert all(len(selection.analysis_data(g).encode()) <= 1000 for g in groups)
    with pytest.raises(ApiError, match="capacity"):
        list(selection.chunks(words, settings.model_copy(update={"ai_max_chunks": 1})))


def test_official_http_adapter_bounded_auth_no_redirects(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://local/local",
        deepgram_api_key="fictional",
        gemini_api_key="fictional",
        deepgram_model="fixture",
        deepgram_version="v1",
        gemini_model="fixture",
    )
    seen = []

    def transport(req):
        seen.append(req)
        if req.url.host == "api.deepgram.com":
            assert req.headers["authorization"] == "Token fictional"
            assert req.url.params["language"] == "en" and req.read() == b"audio"
            return httpx.Response(200, json=dg_payload())
        assert req.headers["x-goog-api-key"] == "fictional" and "key" not in req.url.params
        return httpx.Response(302, headers={"location": "http://localhost"})

    providers = HTTPProviders(settings, transport=httpx.MockTransport(transport))
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    assert providers.transcribe(path)["status"] == 200
    assert providers.analyze(gemini_body("bounded", settings))["status"] == 302
    assert len(seen) == 2


@pytest.mark.parametrize("status", [429, 500, 503, 401, 302])
def test_http_failures_no_implicit_paid_retries(processing, monkeypatch, status):
    simulator = Simulator()

    def rejected(path):
        simulator.calls.append("deepgram")
        return {"status": status, "body": {"error": "synthetic rejection"}}

    simulator.transcribe = rejected
    result = drive(processing, monkeypatch, simulator)
    assert result[0] == "FAILED"
    assert len(simulator.calls) == (3 if status == 429 else 1)
    with processing[0][0]() as db:
        attempts = list(db.scalars(select(SpendAttempt)))
        assert all(a.state == ("VOID" if status == 429 else "UNKNOWN") for a in attempts)


def test_response_checkpoint_db_failure_recovers_without_second_call(processing, monkeypatch):
    simulator = Simulator()
    original = ai.checkpoint_response
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated DB outage after fsynced response")
        return original(*args)

    monkeypatch.setattr(ai, "checkpoint_response", fail_once)
    assert drive(processing, monkeypatch, simulator)[0] == "SUGGESTIONS_READY"
    assert simulator.calls == ["deepgram", "gemini"]


def test_concurrent_duplicate_workers_one_provider_execution(processing, monkeypatch):
    simulator = Simulator()
    monkeypatch.setattr(ai, "HTTPProviders", lambda _: simulator)
    factory, _, settings, storage = processing[0]
    barrier = Barrier(2)

    def execute():
        barrier.wait(timeout=10)
        worker.run_job(processing[2], 0, factory, settings, storage)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: execute(), range(2)))
    assert simulator.calls == ["deepgram"]
    assert drive(processing, monkeypatch, simulator)[0] == "SUGGESTIONS_READY"
    assert simulator.calls == ["deepgram", "gemini"]


def test_cancel_during_provider_records_usage_releases_once(processing, monkeypatch):
    simulator = Simulator()
    original = simulator.transcribe
    factory, users, _, _ = processing[0]

    def canceled(path):
        with factory() as db:
            service.cancel_job(db, users["alice"], processing[2])
            db.commit()
        return original(path)

    simulator.transcribe = canceled
    assert drive(processing, monkeypatch, simulator)[0] == "CANCELED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == 1
        test_credits.assert_wallet(db, users["alice"], 5, 0)
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0


def test_missing_rates_and_budget_reject_before_provider(processing, monkeypatch):
    simulator = Simulator()
    factory, users, _, _ = processing[0]
    with factory() as db:
        limits = users["ai_limits"].model_copy(update={"per_job_usd": Decimal("0")})
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Disable simulator expenses"),
            "zero-policy",
            users["admin"],
        )
        db.commit()
    assert drive(processing, monkeypatch, simulator) == ("FAILED", "budget_exceeded")
    assert simulator.calls == []


def test_waiting_resume_and_hold_timeout(processing, monkeypatch):
    factory, users, settings, storage = processing[0]
    disabled = settings.model_copy(update={"ai_enabled": False})
    worker.run_job(processing[2], 0, factory, disabled, storage)
    assert ai.resume_waiting(factory, disabled) == 0
    assert ai.resume_waiting(factory, settings) == 1
    assert drive(processing, monkeypatch, Simulator())[0] == "SUGGESTIONS_READY"
    with factory() as db:
        db.get(Job, processing[2]).updated_at = utcnow() - timedelta(days=2)
        db.commit()
    cleanup(factory, storage)
    with factory() as db:
        assert db.get(Job, processing[2]).state == "CANCELED"
        test_credits.assert_wallet(db, users["alice"], 5, 0)


def test_migration_refuses_populated_provider_history(processing, monkeypatch):
    assert drive(processing, monkeypatch, Simulator())[0] == "SUGGESTIONS_READY"
    factory = processing[0][0]
    with factory().get_bind().begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Refusing"):
            command.downgrade(config, "7e3fcb0834e3")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "91731e381b3a"


def test_private_endpoints_idor_revocation_and_actual_data(processing, monkeypatch, app, client):
    assert drive(processing, monkeypatch, Simulator())[0] == "SUGGESTIONS_READY"
    factory, users, settings, storage = processing[0]
    app.state.session_factory = factory
    app.state.settings = settings
    test_credits.authenticate(client, app, users["bob"])
    video = processing[1]
    for suffix in ("transcript", "suggestions"):
        assert client.get(f"/api/v1/videos/{video}/{suffix}").status_code == 404
    test_credits.authenticate(client, app, users["alice"])
    response = client.get(f"/api/v1/videos/{video}/transcript")
    assert response.status_code == 200 and len(response.json()["data"]["words"]) == 5
    response = client.get(f"/api/v1/videos/{video}/suggestions")
    assert response.status_code == 200 and response.json()["rendered"] is False
    assert len(response.json()["items"]) == 1
    assert client.get(f"/api/v1/videos/{video}/suggestions?job_id={uuid4()}").status_code == 404
    with factory() as db:
        service.delete_video(db, users["alice"], video)
        db.commit()
    for suffix in ("transcript", "suggestions"):
        assert client.get(f"/api/v1/videos/{video}/{suffix}").status_code == 404
    cleanup(factory, storage)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0
        assert db.scalar(select(func.count()).select_from(ClipSuggestion)) == 0
        assert all(r.response is None for r in db.scalars(select(AIRequest)))
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == 3


@pytest.mark.parametrize(
    "boundary", ["lost_response", "receipt_before_db", "usage_before_transcript"]
)
def test_worker_crash_no_blind_paid_retry(processing, monkeypatch, boundary):
    factory, users, settings, storage = processing[0]
    simulator = Simulator()
    monkeypatch.setattr(ai, "HTTPProviders", lambda _: simulator)
    if boundary == "lost_response":
        simulator.dg = SystemExit("simulated lost remote response")
    elif boundary == "receipt_before_db":
        original = ai.checkpoint_response
        monkeypatch.setattr(
            ai, "checkpoint_response", lambda *args: (_ for _ in ()).throw(SystemExit())
        )
    else:
        original = selection.transcript
        monkeypatch.setattr(
            selection, "transcript", lambda *args: (_ for _ in ()).throw(SystemExit())
        )
    with pytest.raises(SystemExit):
        worker.run_job(processing[2], 0, factory, settings, storage)
    if boundary == "receipt_before_db":
        monkeypatch.setattr(ai, "checkpoint_response", original)
    elif boundary == "usage_before_transcript":
        monkeypatch.setattr(selection, "transcript", original)
    with factory() as db:
        row = db.get(Job, processing[2])
        assert row.state == "RUNNING"
        row.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    worker.recover(factory)
    result = drive(processing, monkeypatch, simulator)
    assert result[0] == ("FAILED" if boundary == "lost_response" else "SUGGESTIONS_READY")
    assert simulator.calls.count("deepgram") == 1
    with factory() as db:
        attempts = list(db.scalars(select(SpendAttempt)))
        if boundary == "lost_response":
            assert attempts[0].state == "UNKNOWN"
            test_credits.assert_wallet(db, users["alice"], 5, 0)
        else:
            assert len(attempts) == 3 and all(a.state == "RECORDED" for a in attempts)


def test_actual_database_commit_failure_after_success_reuses_checkpoint(processing, monkeypatch):
    factory = processing[0][0]
    failed = False

    def fail_commit(db):
        nonlocal failed
        if not failed and any(isinstance(row, Transcript) for row in db.identity_map.values()):
            failed = True
            raise OperationalError("synthetic commit failure", None, Exception("simulated outage"))

    event.listen(factory.class_, "before_commit", fail_commit)
    simulator = Simulator()
    try:
        assert drive(processing, monkeypatch, simulator)[0] == "SUGGESTIONS_READY"
        assert failed
        assert simulator.calls == ["deepgram", "gemini"]
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)


@pytest.mark.parametrize(
    "dimension",
    ["per_job_usd", "user_daily_usd", "user_monthly_usd", "global_daily_usd", "global_monthly_usd"],
)
def test_gemini_pair_admission_rolls_back_both_dimensions(processing, monkeypatch, dimension):
    factory, users, settings, storage = processing[0]
    simulator = Simulator()
    monkeypatch.setattr(ai, "HTTPProviders", lambda _: simulator)
    worker.run_job(processing[2], 0, factory, settings, storage)  # Transcription success, one cost.
    with factory() as db:
        limits = users["ai_limits"].model_copy(update={dimension: Decimal("0.010001")})
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Bound every expense dimension"),
            "restrict-pair",
            users["admin"],
        )
        db.commit()
    assert drive(processing, monkeypatch, simulator) == ("FAILED", "budget_exceeded")
    assert simulator.calls == ["deepgram"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SpendAttempt)) == 1
        test_credits.assert_wallet(db, users["alice"], 5, 0)


def test_usage_includes_thinking_overrun_and_breaker():
    payload = gemini_payload()
    payload["usageMetadata"].update(thoughtsTokenCount=25, totalTokenCount=175)
    assert ai.usage({"status": 200, "body": payload}, "gemini") == [100, 75]
    payload["usageMetadata"]["totalTokenCount"] = 100
    assert ai.usage({"status": 200, "body": payload}, "gemini") is None


def test_actual_usage_overrun_retained_and_breaker_open(processing, monkeypatch):
    payload = gemini_payload()
    payload["usageMetadata"].update(candidatesTokenCount=10000, totalTokenCount=10100)
    assert drive(processing, monkeypatch, Simulator(gemini=payload))[0] == "SUGGESTIONS_READY"
    from zoclip.credits.models import SystemLimits

    with processing[0][0]() as db:
        assert db.get(SystemLimits, 1).breaker is True
        assert max(db.scalars(select(ProviderUsage.units))) == 10000


def test_model_rate_mismatch_blocks_paid_call(processing, monkeypatch):
    media, video, job = processing
    factory, users, settings, storage = media
    changed = settings.model_copy(update={"deepgram_diarize": True})
    simulator = Simulator()
    assert drive(((factory, users, changed, storage), video, job), monkeypatch, simulator) == (
        "FAILED",
        "model_rate_mismatch",
    )
    assert simulator.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        {"ai_enabled": True, "analysis_provider": "gemini"},
        {"deepgram_language": "ur"},
        {"ai_min_clip_seconds": 60, "ai_max_clip_seconds": 10},
        {"gemini_model": "../untrusted"},
        {"ai_provider_timeout_seconds": 999},
    ],
)
def test_ai_configuration_fail_closed(bad):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql+psycopg://local/local", **bad)


def test_adapter_response_size_timeout_and_malformed_data():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://local/local")
    for action in ("timeout", "huge", "malformed"):

        def transport(req, action=action):
            if action == "timeout":
                raise httpx.ReadTimeout("synthetic", request=req)
            return httpx.Response(200, content=b"x" * (300000 if action == "huge" else 3))

        providers = HTTPProviders(settings, transport=httpx.MockTransport(transport))
        if action == "malformed":
            assert providers.analyze({})["body"] is None
        else:
            with pytest.raises(ProviderFailure):
                providers.analyze({})


def test_zero_wallet_cannot_create_paid_ai_job(media, video_bytes):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    with factory() as db:
        money.adjust(
            db,
            users["alice"],
            -5,
            "remove-test-grant",
            users["admin"],
            "Fictional zero-balance regression",
        )
        db.commit()
    with pytest.raises(ApiError) as error:
        test_media.process_job(media, video)
    assert error.value.code == "insufficient_credits"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0


def test_audio_cancellation_removes_subprocess_work(media, video_bytes):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    with factory() as db:
        object_id = db.get(SourceVideo, video).object_id
    from zoclip.ai.audio import extract

    temp = uuid4()

    def revoked():
        raise ApiError(409, "job_canceled", "Synthetic revocation")

    try:
        with pytest.raises(ApiError, match="revocation"):
            extract(storage, object_id, temp, os.environ.get("FFMPEG_BINARY", "ffmpeg"), 3, revoked)
    finally:
        storage.delete(temp)
    assert not storage.path(temp).exists()


@pytest.mark.parametrize("receipt", [False, True])
def test_cancel_after_crash_reconciles_receipt_or_unknown(processing, monkeypatch, receipt):
    factory, users, settings, storage = processing[0]
    simulator = Simulator()
    monkeypatch.setattr(ai, "HTTPProviders", lambda _: simulator)
    if receipt:
        monkeypatch.setattr(
            ai, "checkpoint_response", lambda *args: (_ for _ in ()).throw(SystemExit())
        )
    else:
        simulator.dg = SystemExit("lost response")
    with pytest.raises(SystemExit):
        worker.run_job(processing[2], 0, factory, settings, storage)
    with factory() as db:
        service.cancel_job(db, users["alice"], processing[2])
        db.get(Job, processing[2]).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    worker.recover(factory, storage)
    with factory() as db:
        assert db.get(Job, processing[2]).state == "CANCELED"
        assert db.scalar(select(SpendAttempt)).state == ("RECORDED" if receipt else "UNKNOWN")
        test_credits.assert_wallet(db, users["alice"], 5, 0)
    assert simulator.calls == ["deepgram"]
    with factory() as db:
        service.delete_video(db, users["alice"], processing[1])
        db.commit()
    cleanup(factory, storage)
    with factory() as db:
        assert db.scalar(select(AIRequest)).response is None
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == int(receipt)


def test_cancellation_after_admission_before_dispatch_voids_proven_unsent(processing, monkeypatch):
    factory, users, _, _ = processing[0]
    original = ai.checked

    def cancel_after_admission(db, owner, job_id, token):
        if db.scalar(select(func.count()).select_from(AIRequest)):
            with factory() as other:
                service.cancel_job(other, owner, job_id)
                other.commit()
        return original(db, owner, job_id, token)

    monkeypatch.setattr(ai, "checked", cancel_after_admission)
    simulator = Simulator()
    assert drive(processing, monkeypatch, simulator)[0] == "CANCELED"
    assert simulator.calls == []
    with factory() as db:
        assert db.scalar(select(SpendAttempt)).state == "VOID"
        assert db.scalar(select(ProviderUsage)).units == 0
        test_credits.assert_wallet(db, users["alice"], 5, 0)


def test_gemini_chunk_pipeline_reuses_each_exact_result(processing, monkeypatch):
    media, video, job_id = processing
    factory, users, settings, storage = media
    settings = settings.model_copy(update={"ai_chunk_bytes": 1000})
    payload = dg_payload()
    payload["results"]["channels"][0]["alternatives"][0]["words"] = [
        {"word": "é" * 160, "start": i / 2, "end": (i + 1) / 2, "confidence": 0.9} for i in range(5)
    ]
    simulator = Simulator(dg=payload)
    configured = factory, users, settings, storage
    assert drive((configured, video, job_id), monkeypatch, simulator, max_steps=30)[0] == (
        "SUGGESTIONS_READY"
    )
    first_calls = list(simulator.calls)
    assert first_calls.count("deepgram") == 1 and first_calls.count("gemini") > 1
    with factory() as db:
        service.cancel_job(db, users["alice"], job_id)
        db.commit()
    second = test_media.process_job(configured, video, "chunk-cache")
    assert drive((configured, video, second), monkeypatch, simulator, max_steps=30)[0] == (
        "SUGGESTIONS_READY"
    )
    assert simulator.calls == first_calls
