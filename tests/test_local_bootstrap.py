"""Fresh preserved PostgreSQL schemas only; no provider calls or readiness mutations."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import fakeredis
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.auth.models import AuditLog, AuthSession, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.credits.models import SystemLimits
from zoclip.ops.local_bootstrap import (
    ACTION,
    Approval,
    financial_payloads,
    isolated,
    promote,
    verify_manifest,
)


def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://offline@127.0.0.1:55439/zoclip_live_readiness",
        redis_url="redis://127.0.0.1:56389/0",
        media_root="F:/ZoClip-LiveAI/media",
        gemini_model="gemini-3.1-flash-lite",
        deepgram_model="nova-3",
        deepgram_language="en",
        deepgram_version="",
        ai_enabled=False,
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"ai_enabled": True},
        {"app_env": "production"},
        {"database_url": "postgresql+psycopg://offline@127.0.0.1:55439/production"},
        {"redis_url": "redis://127.0.0.1:56389/1"},
        {"media_root": "C:/other"},
    ],
)
def test_target_refuses_changed_scope(changed):
    isolated(settings())
    with pytest.raises(ValueError):
        isolated(Settings(_env_file=None, **{**settings().model_dump(), **changed}))


def test_manifest_hash_and_timestamp(tmp_path):
    proposal = tmp_path / "proposal.md"
    proposal.write_text("approved proposal")
    approval = Approval(
        operation_id=uuid4(),
        admin_id=uuid4(),
        customer_id=uuid4(),
        operator="local-test",
        reason="approved test",
        approved_at=utcnow(),
        approval_evidence="Explicit local-only test approval",
        proposal_sha256=sha256(proposal.read_bytes()).hexdigest(),
    )
    verify_manifest(approval, proposal)
    proposal.write_text("changed")
    with pytest.raises(ValueError):
        verify_manifest(approval, proposal)


def test_financial_evidence_and_exact_payloads():
    config = settings()
    with pytest.raises(ValueError):
        financial_payloads(config, {})
    config = config.model_copy(update={"deepgram_version": "offline-test-pin"})
    evidence = {
        "rate_basis": "approved_public_standard_prices_2026-10-14",
        "nova3_english_batch_confirmed": True,
        "source": "offline test ONLY",
        "verified_at": "2026-10-13",
        "deepgram_version": "offline-test-pin",
    }
    rates, policy = financial_payloads(config, evidence)
    assert [r["max_units"] for r in rates] == [1, 36000, 2048, 520, 1]
    assert [r["unit_usd"] for r in rates] == [
        "0.0043",
        "0.00000025",
        "0.0000015",
        "0.00001",
        "0.001",
    ]
    assert policy["breaker"] is True
    for name in (
        "per_job_usd",
        "user_daily_usd",
        "user_monthly_usd",
        "global_daily_usd",
        "global_monthly_usd",
    ):
        assert policy["limits"][name] == "0.05"
    for changed in (
        {"rate_basis": "unapproved"},
        {"deepgram_version": "other"},
        {"nova3_english_batch_confirmed": False},
    ):
        with pytest.raises(ValueError):
            financial_payloads(config, {**evidence, **changed})


@pytest.fixture
def bootstrap_db(bootstrap_revision):
    url = os.environ.get("ZOCLIP_ACCEPTANCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Saved separate mock PostgreSQL database required")
    parsed = make_url(url)
    assert (parsed.host, parsed.port) == ("127.0.0.1", 55439)
    assert parsed.database.startswith("zoclip_mock_") and parsed.database.endswith("_test")
    schema = "bootstrap_test_" + uuid4().hex
    root = create_engine(url, hide_parameters=True)
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC"},
    )
    with engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, bootstrap_revision)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        customer = User(email="test-customer@example.com", verified=True)
        candidate = User(email="test-admin@example.com", verified=True)
        db.add_all([customer, candidate])
        db.flush()
        for action in ("auth.verification_requested", "auth.email_verified", "auth.login"):
            db.add(
                AuditLog(
                    actor_id=candidate.id,
                    target_id=candidate.id,
                    action=action,
                    request_id=str(uuid4()),
                )
            )
        session = AuthSession(
            user_id=candidate.id,
            token_hash="a" * 64,
            csrf_hash="b" * 64,
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        approval = Approval(
            operation_id=uuid4(),
            admin_id=candidate.id,
            customer_id=customer.id,
            operator="offline test",
            reason="Explicit mock bootstrap approval",
            approved_at=utcnow(),
            approval_evidence="Offline mock-only bootstrap approval",
            proposal_sha256="0" * 64,
        )
    try:
        yield factory, approval, session.id
    finally:
        engine.dispose()
        root.dispose()  # Preserve every schema, no reset/drop.


def test_atomic_promotion_rollback_replay_and_sessions(bootstrap_db):
    factory, approval, session_id = bootstrap_db
    with factory() as db:
        promote(db, approval)
        db.rollback()
    with factory() as db:
        assert db.get(User, approval.admin_id).role == "customer"
        assert db.get(AuthSession, session_id).revoked_at is None
        assert (
            db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == ACTION))
            == 0
        )
        audit = promote(db, approval)
        db.commit()
    with factory() as db:
        assert promote(db, approval) == audit
        db.commit()
        assert db.get(User, approval.customer_id).role == "customer"
        assert db.get(AuthSession, session_id).revoked_at is not None
        event = db.get(AuditLog, audit)
        assert event.actor_id is None and event.request_id == str(approval.operation_id)
    with factory() as db, pytest.raises(ValueError):
        promote(db, approval.model_copy(update={"operation_id": uuid4()}))


def test_concurrent_bootstrap_has_one_audit_event(bootstrap_db):
    factory, approval, _ = bootstrap_db

    def execute():
        with factory() as db:
            event = promote(db, approval)
            db.commit()
            return event

    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda _: execute(), range(2)))
    assert events[0] == events[1]
    with factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == ACTION))
            == 1
        )


def test_customer_and_breaker_protection(bootstrap_db):
    factory, approval, _ = bootstrap_db
    with factory() as db, pytest.raises(ValueError):
        promote(db, approval.model_copy(update={"admin_id": approval.customer_id}))
    with factory() as db:
        db.get(SystemLimits, 1).breaker = False
        db.commit()
    with factory() as db, pytest.raises(ValueError):
        promote(db, approval)


def test_financial_routes_rbac_csrf_idempotency_and_closed_policy(bootstrap_db):
    from zoclip.core.security import digest
    from zoclip.credits.models import Plan
    from zoclip.main import create_app

    factory, approval, _ = bootstrap_db
    with factory() as db:
        promote(db, approval)
        for uid, secret in ((approval.admin_id, "c" * 64), (approval.customer_id, "d" * 64)):
            db.add(
                AuthSession(
                    user_id=uid,
                    token_hash=digest(secret),
                    csrf_hash=digest("e" * 64),
                    expires_at=utcnow() + timedelta(hours=1),
                )
            )
        plan_id = db.scalars(select(Plan).where(Plan.slug == "free")).one().id
        db.commit()
    app = create_app(settings())
    app.state.session_factory = factory
    app.state.redis = fakeredis.FakeRedis()
    # Use reviewed JSON straight from the sheet, avoiding a mirrored plan definition.
    sheet = Path("docs/ONE_SHOT_APPROVAL_SHEET.md").read_text(encoding="utf-8")
    plan = json.loads(sheet.split("```json\n")[1].split("\n```")[0])
    from zoclip.core.security import COOKIE_NAME

    with TestClient(app, base_url="https://localhost") as client:
        client.cookies.set(COOKIE_NAME, "d" * 64)
        headers = {
            "Origin": settings().public_app_url,
            "X-CSRF-Token": "e" * 64,
            "Idempotency-Key": "acceptance-v1-plan",
        }
        endpoint = f"/api/v1/admin/plans/{plan_id}/versions"
        assert client.post(endpoint, json=plan, headers=headers).status_code == 403
        client.cookies.set(COOKIE_NAME, "c" * 64)
        assert (
            client.post(
                endpoint, json=plan, headers={**headers, "X-CSRF-Token": "wrong"}
            ).status_code
            == 403
        )
        result = client.post(endpoint, json=plan, headers=headers)
        assert result.status_code == 200
        assert client.post(endpoint, json=plan, headers=headers).json()["id"] == result.json()["id"]
        endpoint = f"/api/v1/admin/users/{approval.customer_id}/credit-adjustments"
        headers["Idempotency-Key"] = "acceptance-v1-credit"
        credit = {"amount": 1, "reason": "One isolated 27-second acceptance job; one output only"}
        assert client.post(endpoint, json=credit, headers=headers).status_code == 200
        assert client.post(endpoint, json=credit, headers=headers).json()["available_after"] == 1
        assert (
            client.post(endpoint, json={**credit, "amount": 2}, headers=headers).status_code == 409
        )
        config = settings().model_copy(update={"deepgram_version": "mock-batch-pin"})
        rates, policy = financial_payloads(
            config,
            {
                "rate_basis": "approved_public_standard_prices_2026-10-14",
                "nova3_english_batch_confirmed": True,
                "source": "offline mock",
                "verified_at": "2026-10-13",
                "deepgram_version": "mock-batch-pin",
            },
        )
        ids = []
        for rate in rates:
            headers["Idempotency-Key"] = "acceptance-v1-rate-" + rate["component"]
            result = client.post("/api/v1/admin/cost-rates", json=rate, headers=headers)
            assert result.status_code == 200
            ids.append(result.json()["id"])
        policy["limits"]["rate_ids"] = ids
        headers["Idempotency-Key"] = "acceptance-v1-policy-closed"
        result = client.post("/api/v1/admin/limits/versions", json=policy, headers=headers)
        assert result.status_code == 200 and result.json()["breaker"] is True
