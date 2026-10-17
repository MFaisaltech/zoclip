"""Focused M5 contracts, isolation and admin actions in fresh preserved mock schemas."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import fakeredis
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.auth.models import AuditLog, AuthSession
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits.models import CreditReservation, Quote, SystemLimits
from zoclip.main import create_app


@pytest.fixture
def dashboard(tmp_path):
    from test_credits import seed

    url = os.environ.get("ZOCLIP_DASHBOARD_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Separate mock PostgreSQL URL required")
    parsed = make_url(url)
    assert (parsed.database or "").startswith("zoclip_mock_")
    assert (parsed.database or "").endswith("_test")
    schema = "billing_dashboard_" + uuid4().hex
    root = create_engine(url, hide_parameters=True)
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "options": f"-c search_path={schema} -c timezone=UTC",
        },
    )
    with engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    people = seed(factory)
    # Test-only fictional policies/credits. Never point this fixture at the runtime schema.
    with factory() as db:
        db.get(SystemLimits, 1).breaker = True
        db.commit()
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=url,
        ai_enabled=False,
        media_root=str(tmp_path),
        cookie_secure=False,
    )
    app = create_app(settings)
    app.state.session_factory = factory
    app.state.redis = fakeredis.FakeRedis()
    try:
        with TestClient(app) as client:
            yield client, factory, people
    finally:
        engine.dispose()
        root.dispose()  # Preserve schema and evidence; no drop/downgrade/reset.


def login(client, factory, owner):
    raw, csrf = uuid4().hex, uuid4().hex
    with factory() as db:
        db.add(
            AuthSession(
                user_id=owner,
                token_hash=digest(raw),
                csrf_hash=digest(csrf),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        db.commit()
    client.cookies.set(COOKIE_NAME, raw)
    return {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "dashboard-reviewed-change",
    }


def reservation(factory, owner, price, state, credits, created=None, updated=None):
    with factory() as db:
        quote = Quote(
            user_id=owner,
            price_version_id=price,
            operation_key=uuid4().hex,
            payload_hash="0" * 64,
            request={},
            credits=credits,
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(quote)
        db.flush()
        row = CreditReservation(
            user_id=owner,
            quote_id=quote.id,
            job_id=uuid4(),
            credits=credits,
            state=state,
            created_at=created or utcnow(),
            updated_at=updated or utcnow(),
        )
        db.add(row)
        db.commit()
        return row.id


def test_overview_matches_quota_semantics_and_is_owner_scoped(dashboard):
    client, factory, people = dashboard
    owner, other = people["alice"], people["bob"]
    old = utcnow() - timedelta(days=45)
    for who, state, credits, created, updated in (
        (owner, "HELD", 2, old, old),
        (owner, "SETTLED", 3, old, utcnow()),
        (owner, "RELEASED", 4, utcnow(), utcnow()),
        (owner, "SETTLED", 7, old, old),
        (other, "HELD", 99, old, old),
    ):
        reservation(factory, who, people["prices"]["free"], state, credits, created, updated)
    login(client, factory, owner)
    data = client.get("/api/v1/me/billing").json()
    assert data["daily_used_credits"] == data["monthly_used_credits"] == 5
    assert data["held_credits"] == 2 and data["settled_credits"] == 10
    assert data["released_credits"] == 4
    assert data["plan"]["slug"] == "free" and data["access_source"] == "free_default"
    assert data["checkout_available"] is False and data["auto_renews"] is False
    assert data["day_starts_at"].endswith("Z")


def test_reservation_pagination_cannot_expose_other_owner(dashboard):
    client, factory, people = dashboard
    for who in (people["alice"], people["alice"], people["bob"]):
        reservation(factory, who, people["prices"]["free"], "HELD", 1)
    login(client, factory, people["alice"])
    first = client.get("/api/v1/me/credit-reservations?limit=1").json()
    second = client.get(
        "/api/v1/me/credit-reservations",
        params={
            "limit": 1,
            "cursor": first["next_cursor"],
        },
    ).json()
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_cursor"] is None
    assert client.get("/api/v1/me/credit-reservations?limit=101").status_code == 422


def test_admin_reads_deny_anonymous_and_customer_before_data_access(dashboard):
    client, factory, people = dashboard
    paths = [
        "/api/v1/admin/dashboard",
        "/api/v1/admin/customers",
        "/api/v1/admin/jobs",
        f"/api/v1/admin/customers/{people['bob']}/billing",
    ]
    for path in paths:
        assert client.get(path).status_code == 401
    login(client, factory, people["alice"])
    for path in paths:
        assert client.get(path).status_code == 403


def test_admin_customer_search_pagination_and_audit(dashboard):
    client, factory, people = dashboard
    login(client, factory, people["admin"])
    data = client.get("/api/v1/admin/customers?limit=1").json()
    assert len(data["items"]) == 1 and data["next_cursor"]
    email = data["items"][0]["email"]
    found = client.get("/api/v1/admin/customers", params={"search": email}).json()
    assert len(found["items"]) == 1
    assert client.get("/api/v1/admin/customers?search=%25").json()["items"] == []
    assert client.get(f"/api/v1/admin/customers/{people['alice']}/billing").status_code == 200
    assert client.get(f"/api/v1/admin/customers/{people['admin']}/billing").status_code == 404
    overview = client.get("/api/v1/admin/dashboard").json()
    assert overview["customers"] == 2 and overview["spending_blocked"] is True
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "billing.dashboard_read")
            )
            == 1
        )
        assert db.get(SystemLimits, 1).breaker is True


def test_existing_admin_adjustment_retains_csrf_idempotency_and_audit(dashboard):
    client, factory, people = dashboard
    url = f"/api/v1/admin/users/{people['alice']}/credit-adjustments"
    headers = login(client, factory, people["admin"])
    body = {"amount": 2, "reason": "Reviewed offline dashboard adjustment"}
    assert client.post(url, json=body).status_code == 403
    first = client.post(url, json=body, headers=headers)
    second = client.post(url, json=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert client.post(url, json={**body, "amount": 3}, headers=headers).status_code == 409
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "credits.admin_adjust",
                    AuditLog.target_id == UUID(first.json()["id"]),
                )
            )
            == 1
        )
        assert db.get(SystemLimits, 1).breaker is True


def test_plan_versions_and_staff_access_reuse_audited_financial_routes(dashboard):
    client, factory, people = dashboard
    headers = login(client, factory, people["admin"])
    catalog = client.get("/api/v1/plans").json()
    plan = next(p for p in catalog if p["slug"] == "creator")
    body = {k: v for k, v in plan["price"].items() if k != "id"}
    body["reason"] = "Reviewed offline plan configuration"
    path = f"/api/v1/admin/plans/{plan['id']}/versions"
    result = client.post(path, json=body, headers=headers)
    assert result.status_code == 200
    assert client.post(path, json=body, headers=headers).json()["id"] == result.json()["id"]
    access_path = f"/api/v1/admin/users/{people['alice']}/entitlements"
    access = {"price_version_id": plan["price"]["id"], "reason": "Reviewed offline staff award"}
    result = client.post(access_path, json=access, headers=headers)
    assert result.status_code == 200
    assert (
        client.post(access_path, json=access, headers=headers).json()["id"] == result.json()["id"]
    )
    login(client, factory, people["alice"])
    applied = client.get("/api/v1/me/billing").json()
    assert applied["plan"]["price"]["id"] == plan["price"]["id"]
    assert applied["access_source"] == "entitlement" and applied["access_ends_at"]
    with factory() as db:
        assert db.get(SystemLimits, 1).breaker is True
