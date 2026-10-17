"""Closed private ingestion works without provisioning money or a retail catalog."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_credits import authenticate

from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.credits.models import CreditTransaction, PlanPrice, SystemLimits, Wallet
from zoclip.main import create_app
from zoclip.media import service, worker
from zoclip.media.models import Job, SourceVideo, UploadSession
from zoclip.media.storage import LocalStorage


def closed_settings(**overrides):
    return SimpleNamespace(
        private_staging=True,
        ai_enabled=False,
        payment_provider="disabled",
        enable_live_payments=False,
        **overrides,
    )


def missing_catalog(*args):
    raise ApiError(503, "plan_unconfigured", "No current plan allowance is configured.")


@pytest.mark.parametrize("private", [False, True])
def test_catalog_fallback_is_private_only(monkeypatch, private):
    monkeypatch.setattr(service.money, "active_price", missing_catalog)
    db = Mock()
    db.get.return_value = SimpleNamespace(breaker=True)
    settings = closed_settings()
    settings.private_staging = private
    if private:
        assert service.source_duration_limit(db, uuid4(), settings) == 7200
        db.get.assert_called_once_with(SystemLimits, 1)
    else:
        with pytest.raises(ApiError, match="plan_unconfigured"):
            service.source_duration_limit(db, uuid4(), settings)
        db.get.assert_not_called()
    db.commit.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.parametrize(
    "condition", ["missing_breaker", "open_breaker", "ai", "payments", "live_payments"]
)
def test_private_upload_never_opens_financial_controls(monkeypatch, condition):
    monkeypatch.setattr(service.money, "active_price", missing_catalog)
    settings, db = closed_settings(), Mock()
    db.get.return_value = (
        None
        if condition == "missing_breaker"
        else SimpleNamespace(breaker=condition != "open_breaker")
    )
    if condition == "ai":
        settings.ai_enabled = True
    if condition == "payments":
        settings.payment_provider = "mock"
    if condition == "live_payments":
        settings.enable_live_payments = True
    with pytest.raises(ApiError, match="spending_disabled"):
        service.source_duration_limit(db, uuid4(), settings)
    db.commit.assert_not_called()
    db.add.assert_not_called()


def test_disabled_plan_does_not_fall_back(monkeypatch):
    def disabled(*args):
        raise ApiError(503, "plan_unavailable", "Disabled")

    monkeypatch.setattr(service.money, "active_price", disabled)
    with pytest.raises(ApiError, match="plan_unavailable"):
        service.source_duration_limit(Mock(), uuid4(), closed_settings())


def test_configured_plan_duration_still_applies(monkeypatch):
    rules = dict(
        credits_per_minute=1,
        credits_per_output=0,
        credits_per_edit=0,
        captions_credits=0,
        reframe_credits=0,
        max_source_seconds=60,
        max_outputs=1,
        max_edits=0,
        max_concurrent_jobs=1,
        daily_credits=1,
        monthly_credits=1,
    )
    monkeypatch.setattr(service.money, "active_price", lambda *args: SimpleNamespace(rules=rules))
    assert service.source_duration_limit(Mock(), uuid4(), closed_settings()) == 60


def test_private_http_upload_finalization_and_list_without_prices_or_credits(app, monkeypatch):
    """Real PostgreSQL, authenticated HTTP parts, real ffprobe and owner-scoped list."""
    settings = Settings(
        _env_file=None,
        app_env="production",
        private_staging=True,
        staging_site_domain="example.com",
        public_app_url="https://app.staging.example.com",
        api_public_url="https://api.staging.example.com:8443",
        allowed_hosts=["api.staging.example.com"],
        database_url=app.state.settings.database_url,
        media_root=app.state.settings.media_root,
        media_part_bytes=65536,
    )
    application = create_app(settings)
    application.state.session_factory = app.state.session_factory
    application.state.redis.close()
    application.state.redis = app.state.redis
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda self: 1024**4)
    factory = application.state.session_factory
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PlanPrice)) == 0
        assert db.get(SystemLimits, 1).breaker is True
        user = User(email=f"upload-{uuid4()}@example.com", verified=True)
        db.add(user)
        db.flush()
        owner = user.id
        db.commit()
    content = Path("tests/fixtures/source.mp4").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    with TestClient(application, base_url=settings.api_public_url) as client:
        headers = authenticate(client, application, owner) | {"Origin": settings.public_app_url}
        response = client.post(
            "/api/v1/uploads",
            headers=headers,
            json=dict(size_bytes=len(content), sha256=digest, rights_attested=True),
        )
        assert response.status_code == 201, response.text
        upload = response.json()
        for number, start in enumerate(range(0, len(content), upload["part_bytes"])):
            part = content[start : start + upload["part_bytes"]]
            received = client.put(
                f"/api/v1/uploads/{upload['id']}/parts/{number}",
                content=part,
                headers=headers
                | {
                    "Content-Type": "application/octet-stream",
                    "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
                },
            )
            assert received.status_code == 200, received.text
        final = client.post(
            f"/api/v1/uploads/{upload['id']}/complete",
            headers=headers | {"Idempotency-Key": "finish"},
        )
        assert final.status_code == 202, final.text
        job = final.json()
        assert job["estimated_credits"] == 0
        assert client.get("/api/v1/videos").json()[0]["id"] == upload["video_id"]
        worker.run_job(UUID(job["id"]), 0, factory, settings, LocalStorage(settings.media_root))
        listed = client.get("/api/v1/videos").json()
        assert listed[0]["state"] == "READY"
        assert listed[0]["metadata_json"]["sha256"] == digest
        with factory() as db:
            video = db.get(SourceVideo, UUID(upload["video_id"]))
            assert LocalStorage(settings.media_root).path(video.object_id).read_bytes() == content
            assert db.get(UploadSession, UUID(upload["id"])).state == "COMPLETE"
            assert db.get(Job, UUID(job["id"])).state == "COMPLETED"
            assert db.scalar(select(func.count()).select_from(PlanPrice)) == 0
            assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 0
            wallet = db.scalar(select(Wallet).where(Wallet.user_id == owner))
            assert (wallet.available, wallet.reserved) == (0, 0)
            assert db.get(SystemLimits, 1).breaker is True
