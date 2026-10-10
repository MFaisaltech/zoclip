"""Verified fictional sandbox payments; actual PostgreSQL transactions and races."""

import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
import test_credits
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from zoclip.auth.models import AuditLog, User
from zoclip.billing import service as billing
from zoclip.billing.models import (
    BillingOrder,
    BillingRefund,
    EntitlementRevocation,
    PaymentAttempt,
    PaymentEvent,
    RefundRequest,
    StaffPaymentAction,
)
from zoclip.billing.providers import MockSandboxProvider, build_provider, sign_sandbox
from zoclip.billing.schemas import OrderInput, SandboxNotification
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as credits
from zoclip.credits.models import CreditTransaction, Entitlement, Plan, PlanPrice
from zoclip.credits.schemas import PlanVersionInput, QuoteInput

SECRET = "fictional-unit-test-sandbox-secret-000000000000"
REASON = "Explicit sandbox payment verification"
financial_database = test_credits.concurrent_db


def configure(factory, users):
    with factory() as db:
        for slug in ("creator", "pro", "business", "topup"):
            plan = db.scalars(select(Plan).where(Plan.slug == slug)).one()
            price = credits.configure_plan(
                db,
                plan.id,
                PlanVersionInput(
                    price_paisa=15000,
                    included_credits=10,
                    valid_days=0 if slug == "topup" else 30,
                    rules=users["rules"],
                    reason=REASON,
                ),
                "payment-price",
                users["admin"],
            )
            users["prices"][slug] = price.id
        db.commit()


@pytest.fixture
def payments(app):
    users = test_credits.seed(app.state.session_factory, balance=0)
    configure(app.state.session_factory, users)
    provider = MockSandboxProvider(SECRET)
    app.state.payment_provider = provider
    return app.state.session_factory, users, provider


def new_order(payments, key="purchase", slug="creator", owner="alice"):
    factory, users, provider = payments
    with factory() as db:
        row = billing.create_order(
            db, users[owner], OrderInput(price_version_id=users["prices"][slug]), key, provider
        )
        db.commit()
        return row.id


def notification(payments, order_id, **changes):
    factory, _, _ = payments
    with factory() as db:
        order = db.get(BillingOrder, order_id)
        data = SandboxNotification(
            event_id="event-" + uuid4().hex,
            order_id=order_id,
            reference=billing.reference(db, order),
            status="SUCCEEDED",
            amount_paisa=order.amount_paisa,
            currency="PKR",
            occurred_at=utcnow(),
        )
    return data.model_copy(update=changes)


def evidence(provider, data):
    body, headers = sign_sandbox(data, SECRET)
    return provider.verify_notification(body, {k.lower(): v for k, v in headers.items()})


def apply(payments, data):
    factory, _, provider = payments
    with factory() as db:
        row = billing.apply_event(db, evidence(provider, data))
        db.commit()
        return row.state


def post(client, data, **headers):
    body, signed = sign_sandbox(data, SECRET)
    return client.post("/api/v1/billing/webhooks/mock", content=body, headers=signed | headers)


def balance(payments, expected):
    factory, users, _ = payments
    with factory() as db:
        wallet = credits.lock_wallet(db, users["alice"], active_required=False)
        assert (wallet.available, wallet.reserved) == expected
        credits.reconcile(db, wallet)


def test_api_order_spoof_return_csrf_idempotence_and_no_secret(client, app, payments):
    _, users, _ = payments
    headers = test_credits.authenticate(client, app, users["alice"])
    payload = {"price_version_id": str(users["prices"]["creator"])}
    assert client.post("/api/v1/billing/orders", json=payload).status_code == 403
    response = client.post("/api/v1/billing/orders", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    checkout = response.json()
    order_id = checkout["order"]["id"]
    assert checkout["checkout_url"] is None
    assert checkout["order"]["amount_paisa"] == 15000
    assert checkout["order"]["auto_renews"] is False
    assert SECRET not in response.text and "payload_hash" not in response.text
    again = client.post("/api/v1/billing/orders", json=payload, headers=headers)
    assert again.json() == checkout
    changed = client.post(
        "/api/v1/billing/orders",
        json={"price_version_id": str(users["prices"]["pro"])},
        headers=headers,
    )
    assert changed.status_code == 409
    forged = client.get(f"/api/v1/billing/orders/{order_id}?status=success&amount=15000")
    assert forged.json()["state"] == "OPEN"
    balance(payments, (0, 0))


@pytest.mark.parametrize("field", ["amount_paisa", "credits", "user_id", "currency", "return_url"])
def test_client_cannot_choose_financial_fields(client, app, payments, field):
    _, users, _ = payments
    headers = test_credits.authenticate(client, app, users["alice"])
    response = client.post(
        "/api/v1/billing/orders",
        headers=headers,
        json={"price_version_id": str(users["prices"]["creator"]), field: "forged"},
    )
    assert response.status_code == 422
    balance(payments, (0, 0))


def test_signed_payment_ten_duplicates_and_out_of_order_failure(client, app, payments):
    order_id = new_order(payments)
    data = notification(payments, order_id, fee_paisa=25)
    for _ in range(10):
        response = post(client, data)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "PAID"
    assert post(client, notification(payments, order_id, status="FAILED")).json()["state"] == "PAID"
    balance(payments, (10, 0))
    factory, users, _ = payments
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 1
        assert db.scalar(select(func.count()).select_from(Entitlement)) == 1
        events = list(db.scalars(select(PaymentEvent)))
        assert len(events) == 2 and events[0].evidence_hash
        order = db.get(BillingOrder, order_id)
        assert order.grant_id and order.entitlement_id and order.paid_at
        assert db.get(Entitlement, order.entitlement_id).actor_id == users["alice"]


@pytest.mark.parametrize("variant", ["missing", "bad", "body-tamper", "stale", "future"])
def test_bad_signature_grants_zero(client, payments, variant):
    data = notification(payments, new_order(payments))
    body, headers = sign_sandbox(data, SECRET)
    if variant == "missing":
        headers.pop("X-Sandbox-Signature")
    elif variant == "bad":
        headers["X-Sandbox-Signature"] = "0" * 64
    elif variant == "body-tamper":
        body += b" "
    else:
        stamp = str(int(time.time()) + (600 if variant == "future" else -600))
        headers["X-Sandbox-Timestamp"] = stamp
        headers["X-Sandbox-Signature"] = hmac.digest(
            SECRET.encode(), stamp.encode() + b"." + body, "sha256"
        ).hex()
    result = client.post("/api/v1/billing/webhooks/mock", content=body, headers=headers)
    assert result.status_code == 401
    balance(payments, (0, 0))
    with payments[0]() as db:
        assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 0


@pytest.mark.parametrize(
    "change",
    [{"amount_paisa": 1}, {"currency": "USD"}, {"reference": "wrong"}, {"fee_paisa": 15001}],
)
def test_signed_mismatch_grants_zero(client, payments, change):
    data = notification(payments, new_order(payments), **change)
    response = post(client, data)
    assert response.status_code == 409
    balance(payments, (0, 0))


def test_malformed_oversized_and_naive_evidence(client, payments):
    data = notification(payments, new_order(payments))
    assert (
        post(
            client, data.model_copy(update={"occurred_at": utcnow().replace(tzinfo=None)})
        ).status_code
        == 422
    )
    body = b'{"status":"SUCCEEDED"}'
    stamp = str(int(time.time()))
    headers = {
        "X-Sandbox-Timestamp": stamp,
        "X-Sandbox-Signature": hmac.digest(
            SECRET.encode(), stamp.encode() + b"." + body, "sha256"
        ).hex(),
    }
    assert (
        client.post("/api/v1/billing/webhooks/mock", content=body, headers=headers).status_code
        == 422
    )
    assert client.post("/api/v1/billing/webhooks/mock", content=b"x" * 16385).status_code == 413
    balance(payments, (0, 0))


def test_event_id_reuse_changed_payload_rejected(client, payments):
    data = notification(payments, new_order(payments))
    assert post(client, data).status_code == 200
    response = post(client, data.model_copy(update={"status": "REFUNDED"}))
    assert response.status_code == 409
    balance(payments, (10, 0))


def test_alice_bob_isolation_history_and_staff_reads(client, app, payments):
    factory, users, _ = payments
    alice_order = new_order(payments)
    new_order(payments, key="two")
    headers = test_credits.authenticate(client, app, users["alice"])
    first = client.get("/api/v1/billing/history?limit=1").json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = client.get("/api/v1/billing/history?cursor=" + first["next_cursor"]).json()
    assert len(second["items"]) == 1
    assert client.get("/api/v1/admin/payments").status_code == 403
    assert (
        client.post(
            f"/api/v1/admin/payments/{alice_order}/reconcile",
            headers=headers,
            json={"reason": REASON},
        ).status_code
        == 403
    )
    test_credits.authenticate(client, app, users["bob"])
    assert client.get(f"/api/v1/billing/orders/{alice_order}").status_code == 404
    assert client.get("/api/v1/billing/history").json()["items"] == []
    assert client.get(f"/api/v1/billing/history?cursor={alice_order}").status_code == 404
    test_credits.authenticate(client, app, users["admin"])
    assert len(client.get("/api/v1/admin/payments").json()) == 2
    with factory() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "billing.staff_read"))


def test_expired_late_payment_needs_query_and_audit(client, app, payments):
    factory, users, provider = payments
    order_id = new_order(payments)
    with factory() as db:
        order = db.get(BillingOrder, order_id)
        # Fixed clock used only in application policy, without mutating immutable terms.
        future = order.expires_at + timedelta(seconds=1)
    data = notification(payments, order_id, occurred_at=future)
    # Verified fixture evidence bypasses wall-clock future guard to exercise policy.
    verified = evidence(provider, notification(payments, order_id))
    verified = type(verified)("mock", data, hashlib.sha256(b"late-fixture").hexdigest())
    with factory() as db:
        assert billing.apply_event(db, verified).state == "REVIEW"
        db.commit()
    balance(payments, (0, 0))
    headers = test_credits.authenticate(client, app, users["admin"])
    path = f"/api/v1/admin/payments/{order_id}/reconcile"
    # Neither staff authority nor accept_late without provider evidence grants anything.
    assert (
        client.post(path, headers=headers, json={"reason": REASON, "accept_late": True}).json()[
            "order"
        ]["state"]
        == "REVIEW"
    )
    balance(payments, (0, 0))
    provider.test_evidence[data.reference] = verified
    headers["Idempotency-Key"] = "query-late"
    response = client.post(path, headers=headers, json={"reason": REASON, "accept_late": True})
    assert response.status_code == 200 and response.json()["order"]["state"] == "PAID"
    balance(payments, (10, 0))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StaffPaymentAction)) == 2


def test_delayed_delivery_before_expiry_is_accepted(payments, monkeypatch):
    order_id = new_order(payments)
    data = notification(payments, order_id)
    verified = evidence(payments[2], data)
    monkeypatch.setattr(billing, "utcnow", lambda: data.occurred_at + timedelta(hours=2))
    with payments[0]() as db:
        assert billing.view(db.get(BillingOrder, order_id)).state == "EXPIRED"
        assert billing.apply_event(db, verified).state == "PAID"
        db.commit()
    balance(payments, (10, 0))


@pytest.mark.parametrize("kind", ["REFUNDED", "CHARGEBACK"])
def test_reversal_before_success_never_grants(payments, kind):
    order_id = new_order(payments)
    assert apply(payments, notification(payments, order_id, status=kind)) == kind
    assert apply(payments, notification(payments, order_id)) == kind
    balance(payments, (0, 0))
    with payments[0]() as db:
        assert db.scalar(select(func.count()).select_from(Entitlement)) == 0


@pytest.mark.parametrize("kind", ["REFUNDED", "CHARGEBACK"])
def test_reversal_once_revokes_access_and_keeps_nonnegative_wallet(payments, kind):
    order_id = new_order(payments)
    apply(payments, notification(payments, order_id))
    data = notification(payments, order_id, status=kind)
    for _ in range(3):
        assert apply(payments, data) == kind
    balance(payments, (0, 0))
    factory, users, _ = payments
    with factory() as db:
        refund = db.scalars(select(BillingRefund)).one()
        assert (refund.recovered_credits, refund.unrecovered_credits) == (10, 0)
        assert db.scalar(select(func.count()).select_from(EntitlementRevocation)) == 1
        assert credits.active_price(db, users["alice"]).id == users["prices"]["free"]


def test_spent_and_reserved_credits_leave_exposure_and_hold_account(payments):
    factory, users, _ = payments
    order_id = new_order(payments)
    apply(payments, notification(payments, order_id))
    with factory() as db:
        quote = credits.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=120, output_count=1, captions=False, reframe=False),
            "hold",
        )
        reservation = credits.reserve(db, users["alice"], quote.id, uuid4(), "hold")
        db.commit()
        reservation_id = reservation.id
    assert apply(payments, notification(payments, order_id, status="CHARGEBACK")) == "CHARGEBACK"
    balance(payments, (0, 2))
    with factory() as db:
        refund = db.scalars(select(BillingRefund)).one()
        assert refund.unrecovered_credits == 2
        assert db.get(User, users["alice"]).status == "disabled"
        credits.finish(
            db,
            users["alice"],
            reservation_id,
            "release-held",
            success=False,
            evidence="fixture-final-cancellation",
        )
        db.commit()
    # Released credits stay blocked by the disabled account until audited risk review.
    balance(payments, (2, 0))


def test_refund_intent_is_unknown_until_verified_and_not_reexecuted(
    client, app, payments, monkeypatch
):
    factory, users, provider = payments
    order_id = new_order(payments)
    apply(payments, notification(payments, order_id))
    headers = test_credits.authenticate(client, app, users["admin"])
    calls = []

    def uncertain(ref, key):
        calls.append((ref, key))
        raise ApiError(503, "provider_uncertain", "Reconciliation required.")

    monkeypatch.setattr(provider, "refund_if_supported", uncertain)
    path = f"/api/v1/admin/payments/{order_id}/refund"
    assert client.post(path, headers=headers, json={"reason": REASON}).status_code == 503
    replay = client.post(path, headers=headers, json={"reason": REASON})
    assert replay.status_code == 200 and replay.json()["state"] == "UNKNOWN"
    assert len(calls) == 1
    balance(payments, (10, 0))
    data = notification(payments, order_id, status="REFUNDED")
    provider.test_evidence[data.reference] = evidence(provider, data)
    headers["Idempotency-Key"] = "query-refund"
    response = client.post(
        f"/api/v1/admin/payments/{order_id}/reconcile", headers=headers, json={"reason": REASON}
    )
    assert response.status_code == 200 and response.json()["order"]["state"] == "REFUNDED"
    with factory() as db:
        assert db.scalars(select(RefundRequest)).one().state == "CONFIRMED"
    balance(payments, (0, 0))


def test_refund_confirmation_and_query_mismatched_order(client, app, payments):
    _, users, provider = payments
    order_id = new_order(payments)
    other = new_order(payments, key="other", owner="bob")
    apply(payments, notification(payments, order_id))
    data = notification(payments, order_id, status="REFUNDED")
    headers = test_credits.authenticate(client, app, users["admin"])
    provider.test_evidence[data.reference] = evidence(provider, notification(payments, other))
    path = f"/api/v1/admin/payments/{order_id}/reconcile"
    assert client.post(path, headers=headers, json={"reason": REASON}).status_code == 409
    provider.test_evidence[data.reference] = evidence(provider, data)
    result = client.post(
        f"/api/v1/admin/payments/{order_id}/refund", headers=headers, json={"reason": REASON}
    )
    assert result.status_code == 200 and result.json()["state"] == "CONFIRMED"
    balance(payments, (0, 0))


@pytest.mark.parametrize(
    "slug,days", [("creator", 30), ("pro", 30), ("business", 30), ("topup", 0)]
)
def test_prepaid_versions_and_topup_terms(payments, slug, days):
    order_id = new_order(payments, slug=slug)
    apply(payments, notification(payments, order_id))
    with payments[0]() as db:
        order = db.get(BillingOrder, order_id)
        entitlement = db.get(Entitlement, order.entitlement_id)
        assert order.valid_days == days
        assert (
            (entitlement.ends_at - entitlement.starts_at).days == 30
            if days
            else entitlement.ends_at is None
        )


def test_atomic_grant_rollback_and_redelivery(payments, monkeypatch):
    order_id = new_order(payments)
    data = notification(payments, order_id)
    original = credits.entry

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated failure after wallet mutation")

    with monkeypatch.context() as patch:
        patch.setattr(credits, "entry", crash)
        with pytest.raises(RuntimeError), payments[0]() as db:
            billing.apply_event(db, evidence(payments[2], data))
    balance(payments, (0, 0))
    with payments[0]() as db:
        assert db.get(BillingOrder, order_id).state == "OPEN"
        assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 0
    assert apply(payments, data) == "PAID"
    balance(payments, (10, 0))


@pytest.mark.parametrize("target", ["order", "attempt", "event", "refund"])
def test_database_terms_and_evidence_are_immutable(payments, target):
    order_id = new_order(payments)
    apply(payments, notification(payments, order_id))
    apply(payments, notification(payments, order_id, status="REFUNDED"))
    statements = {
        "order": "UPDATE billing_orders SET amount_paisa = amount_paisa + 1",
        "attempt": "UPDATE payment_attempts SET reference = 'forged'",
        "event": "DELETE FROM payment_events",
        "refund": "TRUNCATE billing_refunds CASCADE",
    }
    with payments[0]() as db, pytest.raises(DBAPIError):
        db.execute(text(statements[target]))


def test_concurrent_distinct_events_and_reversal_delivery(financial_database):
    factory, users = financial_database
    configure(factory, users)
    payments = factory, users, MockSandboxProvider(SECRET)
    order_id = new_order(payments)
    events = [notification(payments, order_id) for _ in range(10)]
    barrier = Barrier(10)

    def deliver(data):
        barrier.wait()
        return apply(payments, data)

    with ThreadPoolExecutor(max_workers=10) as executor:
        assert list(executor.map(deliver, events)) == ["PAID"] * 10
    # Seed fixture starts Alice with five separate credits; one purchase adds ten.
    balance(payments, (15, 0))
    reversal = notification(payments, order_id, status="CHARGEBACK")
    with ThreadPoolExecutor(max_workers=10) as executor:
        assert list(executor.map(deliver, [reversal] * 10)) == ["CHARGEBACK"] * 10
    balance(payments, (5, 0))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BillingRefund)) == 1
        assert db.scalar(select(func.count()).select_from(Entitlement)) == 1
        config = Config("alembic.ini")
        config.attributes["connection"] = db.connection()
        with pytest.raises(RuntimeError, match="payment history"):
            command.downgrade(config, "a580f314c921")


def test_concurrent_duplicate_checkout_and_success_reversal_race(financial_database):
    factory, users = financial_database
    configure(factory, users)
    payments = factory, users, MockSandboxProvider(SECRET)
    barrier = Barrier(10)

    def purchase(_):
        barrier.wait()
        return new_order(payments)

    with ThreadPoolExecutor(max_workers=10) as executor:
        ids = list(executor.map(purchase, range(10)))
    assert len(set(ids)) == 1
    order_id = ids[0]
    race = Barrier(2)

    def deliver(data):
        race.wait()
        return apply(payments, data)

    success = notification(payments, order_id)
    reversal = notification(payments, order_id, status="REFUNDED")
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(deliver, [success, reversal]))
    balance(payments, (5, 0))
    with factory() as db:
        assert db.get(BillingOrder, order_id).state == "REFUNDED"
        assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 1


def test_concurrent_event_id_collision_across_owners(financial_database):
    factory, users = financial_database
    configure(factory, users)
    payments = factory, users, MockSandboxProvider(SECRET)
    alice, bob = new_order(payments), new_order(payments, owner="bob")
    data = [
        notification(payments, order, event_id="shared-provider-event") for order in (alice, bob)
    ]
    barrier = Barrier(2)

    def deliver(event):
        barrier.wait()
        try:
            return apply(payments, event)
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(deliver, data)) == ["PAID", "idempotency_conflict"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
        for owner in (users["alice"], users["bob"]):
            credits.reconcile(db, credits.lock_wallet(db, owner))


def test_paid_order_pins_version_and_prepaid_periods_are_sequential(payments):
    factory, users, _ = payments
    first = new_order(payments)
    with factory() as db:
        old = db.get(PlanPrice, users["prices"]["creator"])
        updated = credits.configure_plan(
            db,
            old.plan_id,
            PlanVersionInput(
                price_paisa=20000,
                included_credits=20,
                valid_days=30,
                rules=users["rules"],
                reason=REASON,
            ),
            "new-retail-version",
            users["admin"],
        )
        db.commit()
        with pytest.raises(ApiError, match="current plan price"):
            billing.create_order(
                db, users["alice"], OrderInput(price_version_id=old.id), "stale-price", payments[2]
            )
        users["prices"]["creator"] = updated.id
    assert apply(payments, notification(payments, first)) == "PAID"
    second = new_order(payments, key="renewal")
    assert apply(payments, notification(payments, second)) == "PAID"
    balance(payments, (30, 0))
    with factory() as db:
        one, two = db.get(BillingOrder, first), db.get(BillingOrder, second)
        assert one.amount_paisa == 15000 and one.credits == 10
        a, b = db.get(Entitlement, one.entitlement_id), db.get(Entitlement, two.entitlement_id)
        assert a.ends_at == b.starts_at


def test_settled_credits_reversal_does_not_restore_spent_balance(payments):
    factory, users, _ = payments
    order_id = new_order(payments)
    apply(payments, notification(payments, order_id))
    with factory() as db:
        quote = credits.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=120, output_count=1, captions=False, reframe=False),
            "successful-fixture-job",
        )
        reservation = credits.reserve(db, users["alice"], quote.id, uuid4(), "success-hold")
        credits.finish(
            db,
            users["alice"],
            reservation.id,
            "fixture-settle",
            success=True,
            evidence="trusted-fixture-deliverable",
        )
        db.commit()
    apply(payments, notification(payments, order_id, status="REFUNDED"))
    balance(payments, (0, 0))
    with factory() as db:
        assert db.scalars(select(BillingRefund)).one().unrecovered_credits == 2


def test_nonascii_signature_is_rejected_before_parsing():
    provider = MockSandboxProvider(SECRET)
    with pytest.raises(ApiError) as error:
        provider.verify_notification(
            b"{}", {"x-sandbox-timestamp": str(int(time.time())), "x-sandbox-signature": "é" * 64}
        )
    assert error.value.code == "invalid_payment_signature"


@pytest.mark.parametrize("mode", ["disabled", "jazzcash"])
def test_unconfigured_and_named_gateway_fail_closed(client, app, mode):
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test@localhost/test",
        payment_provider=mode,
    )
    app.state.payment_provider = build_provider(settings)
    assert client.post(f"/api/v1/billing/webhooks/{mode}", json={}).status_code == 503


@pytest.mark.parametrize(
    "override",
    [
        {"payment_provider": "mock"},
        {"payment_provider": "mock", "payment_mock_webhook_secret": "CHANGE_ME"},
        {
            "payment_provider": "mock",
            "payment_mock_webhook_secret": SECRET,
            "app_env": "production",
        },
        {"enable_live_payments": True},
    ],
)
def test_mock_and_live_configuration_cannot_accidentally_enable(override):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, database_url="postgresql+psycopg://test@localhost/test", **override
        )
