"""30-day plan expiry: unused purchase credits are removed once, safely."""

from datetime import timedelta
from uuid import uuid4

import test_credits
from sqlalchemy import func, select

# Reuse the manual-purchases fixture (verified catalog + funded users).
from test_manual_purchases import input_for, purchases  # noqa: F401

from zoclip.billing import manual
from zoclip.core.db import utcnow
from zoclip.credits import service
from zoclip.credits.models import (
    CreditExpiryEvent,
    CreditReservation,
    CreditTransaction,
    Entitlement,
)

financial_database = test_credits.concurrent_db  # noqa: F401


def activate_long_ago(monkeypatch, db, settings, admin, user, data, key, *, days_ago=31):
    """Run a real activation with the billing clock wound back.

    Entitlements are append-only, so the expired window must be created in
    the past at insert time rather than backdated afterwards.
    """
    past = utcnow() - timedelta(days=days_ago)
    monkeypatch.setattr("zoclip.billing.service.utcnow", lambda: past)
    monkeypatch.setattr("zoclip.billing.manual.utcnow", lambda: past)
    try:
        return manual.activate(db, settings, admin, user, data, key)
    finally:
        monkeypatch.undo()


def test_expiry_removes_only_unused_credits_and_preserves_holds(purchases, monkeypatch):  # noqa: F811
    factory, users, settings = purchases
    expiring = settings.model_copy(update={"credits_expiry_enabled": True})
    with factory() as db:
        activate_long_ago(
            monkeypatch, db, settings, users["admin"], users["alice"], input_for(users), "buy"
        )
        db.commit()
    with factory() as db:
        entitlement = db.scalar(select(Entitlement))
        assert entitlement is not None and entitlement.ends_at is not None
        assert entitlement.ends_at < utcnow()
        from zoclip.credits.schemas import QuoteInput

        quote = service.make_quote(
            db, users["alice"], QuoteInput(source_seconds=60, output_count=1), "quote"
        )
        held = service.reserve(db, users["alice"], quote.id, uuid4(), "reserve")
        reservation_id = held.id
        # The job was admitted inside the window: date its reservation so.
        reservation = db.get(CreditReservation, reservation_id)
        reservation.created_at = entitlement.starts_at + timedelta(days=1)
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 9955, 50)
        # Flag off (the default): the sweep is a no-op, balances untouched.
        assert service.expire_plan_credits(db, settings) == 0
        db.commit()
        test_credits.assert_wallet(db, users["alice"], 9955, 50)
        # Flag on: 10,000 granted - 50 held in-window = 9,950 expires.
        assert service.expire_plan_credits(db, expiring) == 1
        db.commit()
        test_credits.assert_wallet(db, users["alice"], 5, 50)
        entry = db.scalar(select(CreditTransaction).where(CreditTransaction.operation == "EXPIRE"))
        assert entry is not None and entry.available_delta == -9950
        event = db.scalar(select(CreditExpiryEvent))
        assert event is not None and event.deducted_credits == 9950
        # The in-flight job still settles normally after expiry.
        service.finish(
            db, users["alice"], reservation_id, "settle", success=True, evidence="clip-1"
        )
        db.commit()
        test_credits.assert_wallet(db, users["alice"], 5, 0)
        # Processed exactly once: a second sweep changes nothing.
        assert service.expire_plan_credits(db, expiring) == 0
        db.commit()
        test_credits.assert_wallet(db, users["alice"], 5, 0)


def test_expiry_full_balance_without_consumption(purchases, monkeypatch):  # noqa: F811
    factory, users, settings = purchases
    expiring = settings.model_copy(update={"credits_expiry_enabled": True})
    with factory() as db:
        activate_long_ago(
            monkeypatch,
            db,
            settings,
            users["admin"],
            users["bob"],
            input_for(users, slug="pro"),
            "buy-pro",
        )
        db.commit()
    with factory() as db:
        assert service.expire_plan_credits(db, expiring) == 1
        db.commit()
        # Only Bob's own pre-purchase courtesy credits remain.
        test_credits.assert_wallet(db, users["bob"], 5, 0)


def test_unexpired_entitlements_are_never_touched(purchases):  # noqa: F811
    factory, users, settings = purchases
    expiring = settings.model_copy(update={"credits_expiry_enabled": True})
    with factory() as db:
        manual.activate(db, settings, users["admin"], users["alice"], input_for(users), "buy")
        db.commit()
    with factory() as db:
        assert service.expire_plan_credits(db, expiring) == 0
        db.commit()
        test_credits.assert_wallet(db, users["alice"], 10005, 0)
        assert db.scalar(select(func.count()).select_from(CreditExpiryEvent)) == 0
