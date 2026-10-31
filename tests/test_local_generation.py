"""The default local path must reach suggestions without a paid adapter call."""

import os
from pathlib import Path

import pytest
import test_ai
import test_media
from pydantic import ValidationError
from sqlalchemy import select

from zoclip.ai import worker as ai
from zoclip.ai.models import AIRequest, ClipSuggestion
from zoclip.core.config import Settings
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction, Plan, ProviderUsage, SpendAttempt, Wallet
from zoclip.credits.schemas import PlanVersionInput, PolicyInput, QuoteInput
from zoclip.media import service, worker
from zoclip.media.models import Job
from zoclip.media.schemas import ProcessInput
from zoclip.rendering.models import RenderOutput

financial_database = test_ai.financial_database
media = test_ai.media
video_bytes = test_ai.video_bytes
processing = test_ai.processing


def test_local_transcription_and_selection_never_invoke_paid_analysis(processing, monkeypatch):
    configured, video, job = processing
    factory, users, settings, storage = configured
    settings = Settings(
        _env_file=None,
        **(
            settings.model_dump()
            | {
                "transcription_provider": "whisper",
                "analysis_provider": "local",
                "gemini_api_key": "",
                "gemini_model": "",
                "deepgram_api_key": "",
            }
        ),
    )
    simulator = test_ai.Simulator()
    monkeypatch.setattr(ai, "LocalWhisperProviders", lambda _: simulator)
    case = ((factory, users, settings, storage), video, job)
    assert test_ai.drive(case, monkeypatch, simulator) == ("SUGGESTIONS_READY", None)
    assert simulator.calls == ["deepgram"]  # Fake inference label; no HTTP transport exists.
    with factory() as db:
        assert {request.provider for request in db.scalars(select(AIRequest))} == {"whisper"}
        assert list(db.scalars(select(ClipSuggestion)))
        assert not list(db.scalars(select(SpendAttempt)))
        assert not list(db.scalars(select(ProviderUsage)))
        test_ai.test_credits.assert_wallet(db, users["alice"], 4, 1)


def test_local_generation_configuration_requires_no_paid_credentials():
    config = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused/unused_test", ai_enabled=True
    )
    assert config.ai_configured
    assert not config.gemini_api_key.get_secret_value()
    assert not config.deepgram_api_key.get_secret_value()
    assert not config.model_copy(update={"ai_enabled": False}).ai_configured


@pytest.mark.parametrize("provider", ["gemini", "deepgram"])
def test_paid_provider_selection_still_requires_its_credentials(provider):
    choice = (
        {"analysis_provider": "gemini"}
        if provider == "gemini"
        else {"transcription_provider": "deepgram"}
    )
    with pytest.raises(ValidationError, match="selected providers"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://unused/unused_test",
            ai_enabled=True,
            **choice,
        )


@pytest.mark.skipif(
    not os.environ.get("ZOCLIP_REAL_LOCAL_MEDIA"),
    reason="Opt-in authorized media and image-installed Whisper model required",
)
def test_actual_local_inference_auto_render_and_single_settlement(media, monkeypatch):
    factory, users, settings, storage = media
    source = Path(os.environ["ZOCLIP_REAL_LOCAL_MEDIA"])
    video, _ = test_media.ready(media, source.read_bytes())
    configured = test_ai.configure(factory, users, settings)
    settings = Settings(
        _env_file=None,
        **(
            configured.model_dump()
            | {
                "analysis_provider": "local",
                "transcription_provider": "whisper",
                "gemini_api_key": "",
                "gemini_model": "",
                "deepgram_api_key": "",
                "whisper_parallelism": 1,
                "whisper_cpu_threads": 2,
            }
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Paid provider adapter must never execute")

    monkeypatch.setattr(ai.HTTPProviders, "transcribe", forbidden)
    monkeypatch.setattr(ai.HTTPProviders, "analyze", forbidden)
    with factory() as db:
        plan = db.scalar(select(Plan).where(Plan.slug == "free"))
        money.configure_plan(db, plan.id, PlanVersionInput(
            price_paisa=0, included_credits=0, valid_days=0, approved=True,
            rules=users["rules"].model_copy(update={"credits_per_minute": 0, "credits_per_output": 50, "minimum_job_credits": 0}),
            reason="Isolated per-delivered-clip acceptance",
        ), "local-per-clip", users["admin"])
        money.adjust(db, users["alice"], 100, "local-test-credit", users["admin"], "Isolated acceptance allowance", grant=True)
        starting_balance = db.scalar(select(Wallet.available).where(Wallet.user_id == users["alice"]))
        limits = users["ai_limits"].model_copy(
            update={"render_cpu_seconds_per_output": 520, "storage_gb_days_per_output": 2}
        )
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Isolated local render fixture"),
            "local-render",
            users["admin"],
        )
        source_row = db.get(test_media.SourceVideo, video)
        quote = money.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=source_row.metadata_json["duration_seconds"], output_count=1),
            "local-quote",
        )
        request = ProcessInput(video_id=video, quote_id=quote.id, auto_render=True)
        job = service.process(db, users["alice"], request, "local-generate", settings, storage)
        job_id, reservation_id = job.id, job.reservation_id
        assert (
            service.process(db, users["alice"], request, "local-generate", settings, storage).id
            == job_id
        )
        db.commit()
    for _ in range(20):
        with factory() as db:
            row = db.get(Job, job_id)
            generation, state = row.generation, row.state
        if state != "QUEUED":
            break
        worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        row = db.get(Job, job_id)
        assert row.state == "COMPLETED", row.error_code
        assert db.get(CreditReservation, reservation_id).state == "SETTLED"
        assert db.scalar(select(Wallet.available).where(Wallet.user_id == users["alice"])) == starting_balance - 50
        outputs = list(db.scalars(select(RenderOutput).where(RenderOutput.job_id == job_id)))
        assert outputs and all(output.state == "COMPLETE" for output in outputs)
        assert all(storage.path(output.object_id).stat().st_size > 1000 for output in outputs)
        assert {request.provider for request in db.scalars(select(AIRequest))} == {"whisper"}
        before = list(db.scalars(select(CreditTransaction.id)))
        clip_id = outputs[0].clip_id
    # Download the actual rendered MP4 through the authenticated owner endpoint.
    import fakeredis
    from fastapi.testclient import TestClient
    from zoclip.main import create_app
    from test_credits import authenticate

    application = create_app(settings.model_copy(update={"cookie_secure": False}))
    original_engine = application.state.engine
    application.state.session_factory = factory
    application.state.redis = fakeredis.FakeRedis()
    with TestClient(application, base_url="http://localhost:8000") as client:
        authenticate(client, application, users["alice"])
        download = client.get(f"/api/v1/clips/{clip_id}/download")
        assert download.status_code == 200 and download.headers["content-type"] == "video/mp4"
        assert download.content[4:8] == b"ftyp"
        playable = storage.root / "authenticated-download.mp4"
        playable.write_bytes(download.content)
        from zoclip.media.probe import probe
        assert probe(playable, settings.ffprobe_binary)["duration_seconds"] > 0
        evidence = os.environ.get("ZOCLIP_LOCAL_EVIDENCE_DIR")
        if evidence:
            target = Path(evidence); target.mkdir(parents=True, exist_ok=True)
            (target / "generated-authenticated.mp4").write_bytes(download.content)
        authenticate(client, application, users["bob"])
        assert client.get(f"/api/v1/clips/{clip_id}/download").status_code == 404
    original_engine.dispose()
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        assert list(db.scalars(select(CreditTransaction.id))) == before
