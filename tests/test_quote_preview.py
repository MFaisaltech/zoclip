"""Private previews do not provision pricing, financial state, or work."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_credits import authenticate

from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.credits import service
from zoclip.credits.models import (
    CreditReservation,
    CreditTransaction,
    PlanPrice,
    ProviderUsage,
    Quote,
    SpendAttempt,
    SystemLimits,
    Wallet,
)
from zoclip.credits.schemas import QuoteInput
from zoclip.main import create_app
from zoclip.media.models import Job, Outbox

INPUT = QuoteInput(source_seconds=26, output_count=1)


def settings():
    return SimpleNamespace(
        private_staging=True,
        ai_enabled=False,
        payment_provider="disabled",
        enable_live_payments=False,
    )


@pytest.mark.parametrize("condition", ["public", "ai", "payment", "live", "missing", "open"])
def test_preview_fails_closed(condition):
    config, db = settings(), Mock()
    db.get.return_value = (
        None if condition == "missing" else SimpleNamespace(breaker=condition != "open")
    )
    if condition == "public":
        config.private_staging = False
    if condition == "ai":
        config.ai_enabled = True
    if condition == "payment":
        config.payment_provider = "mock"
    if condition == "live":
        config.enable_live_payments = True
    with pytest.raises(ApiError):
        service.preview_quote(db, uuid4(), INPUT, config)
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("approved", [False, True])
def test_preview_uses_only_approved_existing_terms_and_preserves_limits(monkeypatch, approved):
    price = SimpleNamespace(
        id=uuid4(),
        approved=approved,
        rules=dict(
            credits_per_minute=3,
            credits_per_output=2,
            credits_per_edit=1,
            captions_credits=4,
            reframe_credits=5,
            max_source_seconds=60,
            max_outputs=2,
            max_edits=1,
            max_concurrent_jobs=1,
            daily_credits=10,
            monthly_credits=100,
        ),
    )  # Fictional terms in this isolated unit test only.
    monkeypatch.setattr(service, "active_price", lambda *args: price)
    db = Mock()
    db.get.return_value = SimpleNamespace(breaker=True)
    result = service.preview_quote(db, uuid4(), INPUT, settings())
    assert result.credits == (14 if approved else None)
    assert result.price_version_id == price.id
    assert result.processing_enabled is False
    assert not hasattr(result, "id")
    with pytest.raises(ApiError, match="plan_limit"):
        service.preview_quote(db, uuid4(), INPUT.model_copy(update={"output_count": 3}), settings())
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_disabled_plan_is_not_bypassed(monkeypatch):
    def disabled(*args):
        raise ApiError(503, "plan_unavailable", "Disabled")

    monkeypatch.setattr(service, "active_price", disabled)
    db = Mock()
    db.get.return_value = SimpleNamespace(breaker=True)
    with pytest.raises(ApiError, match="plan_unavailable"):
        service.preview_quote(db, uuid4(), INPUT, settings())


def test_private_http_preview_without_catalog_never_dispatches_or_mutates(app):
    config = Settings(
        _env_file=None,
        app_env="production",
        private_staging=True,
        staging_site_domain="example.com",
        public_app_url="https://app.staging.example.com",
        api_public_url="https://api.staging.example.com:8443",
        allowed_hosts=["api.staging.example.com"],
        database_url=app.state.settings.database_url,
        media_root=app.state.settings.media_root,
    )
    application = create_app(config)
    application.state.session_factory = app.state.session_factory
    application.state.redis.close()
    application.state.redis = app.state.redis
    factory = application.state.session_factory
    tables = [
        PlanPrice,
        Quote,
        Wallet,
        CreditReservation,
        CreditTransaction,
        Job,
        Outbox,
        SpendAttempt,
        ProviderUsage,
    ]
    with factory() as db:
        user = User(email=f"preview-{uuid4()}@example.com", verified=True)
        db.add(user)
        db.flush()
        owner = user.id
        db.commit()
        before = [db.scalar(select(func.count()).select_from(table)) for table in tables]
    with TestClient(application, base_url=config.api_public_url) as client:
        assert client.post("/api/v1/jobs/quote-preview", json=INPUT.model_dump()).status_code == 401
        headers = authenticate(client, application, owner) | {"Origin": config.public_app_url}
        assert (
            client.post(
                "/api/v1/jobs/quote-preview",
                headers={"Origin": config.public_app_url},
                json=INPUT.model_dump(),
            ).status_code
            == 403
        )
        for _ in range(2):
            response = client.post(
                "/api/v1/jobs/quote-preview", headers=headers, json=INPUT.model_dump()
            )
            assert response.status_code == 200, response.text
            assert response.json() == dict(
                preview_only=True,
                processing_enabled=False,
                pricing_status="unconfigured",
                price_version_id=None,
                credits=None,
                request=INPUT.model_dump(),
            )
        assert (
            client.post(
                "/api/v1/jobs/quote-preview",
                headers=headers,
                json=INPUT.model_dump() | {"output_count": 101},
            ).status_code
            == 422
        )
        # A preview has no redeemable ID, and its DTO cannot be submitted as a job.
        assert (
            client.post(
                f"/api/v1/videos/{uuid4()}/generate", headers=headers, json=response.json()
            ).status_code
            == 422
        )
        with factory() as db:
            assert [
                db.scalar(select(func.count()).select_from(table)) for table in tables
            ] == before
            assert db.get(SystemLimits, 1).breaker is True
        # The commercial quote path still rejects a missing price; no production bypass.
        assert (
            client.post("/api/v1/jobs/quote", headers=headers, json=INPUT.model_dump()).json()[
                "code"
            ]
            == "plan_unconfigured"
        )
        application.state.settings = config.model_copy(update={"private_staging": False})
        assert (
            client.post(
                "/api/v1/jobs/quote-preview", headers=headers, json=INPUT.model_dump()
            ).status_code
            == 404
        )
