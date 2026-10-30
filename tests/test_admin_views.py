"""Admin views: customers list root-cause regression and readable payments."""

import test_credits
from fastapi.testclient import TestClient
from sqlalchemy import select

# Reuse the manual-purchases fixture (verified catalog + funded users).
from test_manual_purchases import input_for, purchases  # noqa: F401

from zoclip.auth.models import User
from zoclip.billing import manual
from zoclip.main import create_app

financial_database = test_credits.concurrent_db  # noqa: F401


def build_client(factory, settings):
    import fakeredis

    app = create_app(settings.model_copy(update={"cookie_secure": False}))
    app.state.session_factory = factory
    app.state.redis = fakeredis.FakeRedis()
    return app


def test_customers_lists_all_accounts_and_finds_admin_by_exact_email(purchases):  # noqa: F811
    factory, users, settings = purchases
    app = build_client(factory, settings)
    with factory() as db:
        admin_email = db.get(User, users["admin"]).email
        db.add(
            User(
                email="brand-new@example.com",
                password_hash=None,
                verified=True,
                status="active",
                role="customer",
            )
        )
        db.commit()
    with TestClient(app, base_url="http://localhost:8000") as client:
        headers = test_credits.authenticate(client, app, users["admin"])
        # Root-cause regression: the administrator's own account used to be
        # filtered out by role, so this exact-email search returned zero.
        found = client.get(
            "/api/v1/admin/customers", headers=headers, params={"search": admin_email}
        )
        assert found.status_code == 200, found.text
        items = found.json()["items"]
        assert [row["id"] for row in items] == [str(users["admin"])]
        assert items[0]["role"] == "admin"
        everyone = client.get("/api/v1/admin/customers", headers=headers, params={"limit": 100})
        emails = {row["email"] for row in everyone.json()["items"]}
        assert admin_email in emails and "brand-new@example.com" in emails
        # An account with no wallet or purchases still lists, with zeroes.
        fresh = next(
            row for row in everyone.json()["items"] if row["email"] == "brand-new@example.com"
        )
        assert fresh["available_credits"] == 0 and fresh["reserved_credits"] == 0
        assert fresh["plan_slug"] == "free" and fresh["access_ends_at"] is None


def test_payments_view_is_readable_with_plan_and_access_dates(purchases):  # noqa: F811
    factory, users, settings = purchases
    app = build_client(factory, settings)
    with factory() as db:
        manual.activate(db, settings, users["admin"], users["alice"], input_for(users), "buy")
        alice_email = db.get(User, users["alice"]).email
        db.commit()
    with TestClient(app, base_url="http://localhost:8000") as client:
        headers = test_credits.authenticate(client, app, users["admin"])
        rows = client.get("/api/v1/admin/payments", headers=headers, params={"limit": 100})
        assert rows.status_code == 200, rows.text
        mine = [row for row in rows.json() if row["user_id"] == str(users["alice"])]
        assert len(mine) == 1
        row = mine[0]
        assert row["customer_email"] == alice_email
        assert row["customer_name"] == "Alice Example"
        assert row["plan_slug"] == "creator"
        assert row["order"]["amount_paisa"] == 100000
        assert row["order"]["credits"] == 10000
        assert row["order"]["state"] == "PAID"
        assert row["access_starts_at"] is not None and row["access_ends_at"] is not None
        from datetime import datetime

        start = datetime.fromisoformat(row["access_starts_at"])
        end = datetime.fromisoformat(row["access_ends_at"])
        assert (end - start).days == 30


def test_customer_name_is_bound_into_the_idempotent_payload(purchases):  # noqa: F811
    factory, users, settings = purchases
    from zoclip.core.errors import ApiError

    data = input_for(users)
    renamed = data.model_copy(update={"customer_name": "Alice Other"})
    with factory() as db:
        manual.activate(db, settings, users["admin"], users["alice"], data, "named")
        db.commit()
    with factory() as db:
        import pytest

        with pytest.raises(ApiError):
            manual.activate(db, settings, users["admin"], users["alice"], renamed, "named")
        db.rollback()
        orders = list(db.scalars(select(User)))  # sanity: session still usable
        assert orders
