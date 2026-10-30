"""Account admission, execution fences and idempotent release; no paid adapters."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
import test_ai
import test_media
import test_private_staging
from pydantic import ValidationError
from sqlalchemy import select

from zoclip.ai import worker as ai
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.core.generation_access import require_generation_access
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction, PlanPrice
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput
from zoclip.media import service, worker
from zoclip.media.models import Job
from zoclip.ops.staging import verify_closed_runtime
from zoclip.rendering import service as rendering
from zoclip.rendering import worker as render_worker

financial_database = test_ai.financial_database
media = test_ai.media
video_bytes = test_ai.video_bytes
processing = test_ai.processing


def config(owner, **changes):
    return Settings(
        **(
            test_private_staging.BASE
            | {
                "deployment_tier": "protected_staging",
                "staging_generation_enabled": True,
                "staging_generation_user_id": owner,
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"deployment_tier": "production"},
        {"private_staging": False},
        {"staging_generation_user_id": None},
        {"transcription_provider": "deepgram"},
        {"analysis_provider": "gemini"},
        {"ai_enabled": True},
        {"gemini_api_key": "forbidden"},
        {"enable_live_payments": True},
    ],
)
def test_unsafe_activation_rejected(changes):
    with pytest.raises(ValidationError):
        config(uuid4(), **changes)


def test_exactly_one_owner_and_paused_defaults():
    owner = uuid4()
    settings = config(owner)
    require_generation_access(settings, owner)
    assert settings.ai_configured and not settings.ai_enabled
    for candidate in [
        config(owner, staging_generation_enabled=False),
        Settings(**test_private_staging.BASE),
    ]:
        with pytest.raises(ApiError, match="Generation is disabled"):
            require_generation_access(candidate, owner)
    with pytest.raises(ApiError):
        require_generation_access(settings, uuid4())
    assert (
        Settings(
            **(test_private_staging.BASE | {"staging_generation_user_id": ""})
        ).staging_generation_user_id
        is None
    )


def test_enabled_gate_does_not_change_financial_controls():
    engine = Mock()
    verify_closed_runtime(config(uuid4()), engine)
    assert not engine.mock_calls  # Normal financial admission still enforces the breaker.


def test_disallowed_admission_and_direct_execution_never_touch_database():
    settings = config(uuid4())
    owner, job, token = uuid4(), uuid4(), uuid4()
    db, factory, storage = Mock(), Mock(), Mock()
    calls = [
        lambda: service.process(db, owner, Mock(), "request", settings, storage),
        lambda: rendering.select_clips(db, owner, job, [], "request", settings, storage),
        lambda: rendering.rerender(db, owner, job, Mock(), "request", settings, storage),
        lambda: ai.run(job, owner, token, factory, settings, storage),
        lambda: render_worker.run(job, owner, token, factory, settings, storage),
    ]
    for call in calls:
        with pytest.raises(ApiError) as error:
            call()
        assert error.value.code == "staging_generation_disabled"
    assert not db.mock_calls and not factory.mock_calls and not storage.mock_calls


@pytest.mark.parametrize("paused", [False, True])
def test_queued_disallowed_job_releases_once_before_inference(processing, monkeypatch, paused):
    (factory, users, _, storage), _, job_id = processing
    settings = config(
        users["alice"] if paused else users["bob"], staging_generation_enabled=not paused
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Inference must not execute")

    monkeypatch.setattr(ai, "run", forbidden)
    with factory() as db:
        job = db.get(Job, job_id)
        generation, reservation = job.generation, job.reservation_id
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, job_id).error_code == "staging_generation_disabled"
        assert db.get(CreditReservation, reservation).state == "RELEASED"
        test_ai.test_credits.assert_wallet(db, users["alice"], 5, 0)
        before = list(db.scalars(select(CreditTransaction.id)))
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        assert list(db.scalars(select(CreditTransaction.id))) == before


def test_allowed_owner_reaches_local_inference(processing, monkeypatch):
    (factory, users, original, storage), video, job = processing
    settings = Settings(
        **(
            original.model_dump()
            | {
                "_env_file": None,
                **{
                    key: value
                    for key, value in config(users["alice"]).model_dump().items()
                    if key
                    in {
                        "app_env",
                        "private_staging",
                        "deployment_tier",
                        "staging_generation_enabled",
                        "staging_generation_user_id",
                        "staging_site_domain",
                        "public_app_url",
                        "api_public_url",
                        "allowed_hosts",
                        "ai_enabled",
                        "transcription_provider",
                        "analysis_provider",
                        "deepgram_api_key",
                        "gemini_api_key",
                        "email_mode",
                        "cookie_secure",
                        "media_allowed_import_hosts",
                    }
                },
            }
        )
    )
    simulator = test_ai.Simulator()
    monkeypatch.setattr(ai, "LocalWhisperProviders", lambda _: simulator)

    def forbidden(*args, **kwargs):
        pytest.fail("Paid adapter forbidden")

    monkeypatch.setattr(ai, "HTTPProviders", forbidden)
    for _ in range(20):
        with factory() as db:
            row = db.get(Job, job)
            state, generation = row.state, row.generation
        if state != "QUEUED":
            break
        worker.run_job(job, generation, factory, settings, storage)
    with factory() as db:
        row = db.get(Job, job)
        assert row.state == "SUGGESTIONS_READY", row.error_code
        test_ai.test_credits.assert_wallet(db, users["alice"], 4, 1)
    assert simulator.calls == ["deepgram"]  # Simulator label; local adapter only.


def test_allowed_admission_preserves_credit_hold_and_idempotency(media, video_bytes):
    factory, users, original, storage = media
    video, _ = test_media.ready(media, video_bytes)
    settings = config(users["alice"])
    with factory() as db:
        price = db.get(PlanPrice, users["prices"]["free"])
        money.configure_plan(
            db,
            price.plan_id,
            PlanVersionInput(
                price_paisa=price.price_paisa,
                included_credits=price.included_credits,
                valid_days=price.valid_days,
                rules=ConsumptionRules.model_validate(price.rules),
                approved=True,
                reason="Fictional disposable approved fixture",
            ),
            "approved-test-version",
            users["admin"],
        )
        db.commit()
    case = factory, users, settings, storage
    job = test_media.process_job(case, video)
    assert test_media.process_job(case, video) == job
    with factory() as db:
        test_ai.test_credits.assert_wallet(db, users["alice"], 4, 1)
        service.cancel_job(db, users["alice"], job)
        service.cancel_job(db, users["alice"], job)
        db.commit()
    with factory() as db:
        test_ai.test_credits.assert_wallet(db, users["alice"], 5, 0)
