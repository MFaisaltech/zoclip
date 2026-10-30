"""Caller-owned transactions. Lock order: user -> wallet -> order.

No payment grant uses staff adjustments. Only verified adapter evidence may enter
apply_event, and the order, entitlement and append-only wallet grant commit together.
"""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from zoclip.auth.models import User
from zoclip.billing.models import (
    BillingOrder,
    BillingRefund,
    EntitlementRevocation,
    PaymentAttempt,
    PaymentEvent,
    RefundRequest,
    StaffPaymentAction,
)
from zoclip.billing.providers import PaymentProvider, VerifiedNotification
from zoclip.billing.schemas import OrderInput, OrderView
from zoclip.core.db import utcnow
from zoclip.credits import service as credits
from zoclip.credits.models import CreditTransaction, Entitlement, Plan, PlanPrice, Wallet
from zoclip.credits.schemas import ConsumptionRules


def view(order: BillingOrder) -> OrderView:
    result = OrderView.model_validate(order)
    result.sandbox = order.provider != "manual"
    if result.state == "OPEN" and order.expires_at <= utcnow():
        result.state = "EXPIRED"
    return result


def owned_order(db: Session, order_id: UUID, user_id: UUID) -> BillingOrder:
    row = db.scalar(
        select(BillingOrder).where(BillingOrder.id == order_id, BillingOrder.user_id == user_id)
    )
    if row is None:
        credits.fail("not_found", "Order not found.", 404)
    return row


def lock_order(db: Session, order_id: UUID) -> tuple[BillingOrder, Wallet]:
    owner = db.scalar(select(BillingOrder.user_id).where(BillingOrder.id == order_id))
    if owner is None:
        credits.fail("not_found", "Order not found.", 404)
    wallet = credits.lock_wallet(db, owner, active_required=False)
    order = db.scalars(
        select(BillingOrder)
        .where(BillingOrder.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    return order, wallet


def create_order(
    db: Session, owner: UUID, data: OrderInput, key: str, provider: PaymentProvider
) -> BillingOrder:
    # Only the deterministic local adapter is currently enabled. A future network
    # checkout must use durable dispatch and cannot be inserted into this transaction.
    if provider.name != "mock":
        credits.fail("payments_disabled", "Merchant payments are not configured or verified.", 503)
    credits.lock_wallet(db, owner)
    payload = credits.fingerprint(data.model_dump(mode="json"))
    previous = db.scalar(
        select(BillingOrder).where(BillingOrder.user_id == owner, BillingOrder.operation_key == key)
    )
    if previous:
        credits.same(previous.payload_hash, payload)
        return previous
    price = db.get(PlanPrice, data.price_version_id)
    plan = db.get(Plan, price.plan_id) if price else None
    if not price or not plan or not plan.enabled:
        credits.fail("not_found", "Purchasable plan version not found.", 404)
    latest = db.scalar(
        select(PlanPrice.id)
        .where(PlanPrice.plan_id == plan.id)
        .order_by(PlanPrice.created_at.desc(), PlanPrice.id.desc())
        .limit(1)
    )
    if latest != price.id:
        credits.fail("price_stale", "Select the current plan price version.")
    if not ConsumptionRules.model_validate(price.rules).purchasable:
        credits.fail("price_unavailable", "This package is no longer available for purchase.")
    if plan.slug == "free" or price.price_paisa <= 0 or price.included_credits <= 0:
        credits.fail("price_unavailable", "A positive prepaid price and allowance are required.")
    order = BillingOrder(
        user_id=owner,
        price_version_id=price.id,
        provider=provider.name,
        fee_schedule_version=provider.fee_schedule_version,
        amount_paisa=price.price_paisa,
        credits=price.included_credits,
        valid_days=price.valid_days,
        operation_key=key,
        payload_hash=payload,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(order)
    db.flush()
    db.add(
        PaymentAttempt(
            order_id=order.id, provider=provider.name, reference=provider.create_checkout(order.id)
        )
    )
    db.flush()
    return order


def reference(db: Session, order: BillingOrder) -> str:
    return db.scalars(
        select(PaymentAttempt.reference).where(PaymentAttempt.order_id == order.id)
    ).one()


def apply_event(
    db: Session, evidence: VerifiedNotification, *, accept_late: bool = False
) -> BillingOrder:
    data = evidence.notification
    order, wallet = lock_order(db, data.order_id)
    if (
        evidence.provider != order.provider
        or reference(db, order) != data.reference
        or data.amount_paisa != order.amount_paisa
        or data.currency != order.currency
        or data.fee_paisa > data.amount_paisa
        or data.occurred_at < order.created_at - timedelta(seconds=60)
    ):
        credits.fail("payment_mismatch", "Payment evidence does not match the immutable order.")
    payload = credits.fingerprint(data.model_dump(mode="json"))
    now = utcnow()
    # Across owners too: no SELECT-then-INSERT race on provider event IDs.
    db.execute(
        insert(PaymentEvent)
        .values(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            order_id=order.id,
            provider=evidence.provider,
            external_event_id=data.event_id,
            reference=data.reference,
            status=data.status,
            amount_paisa=data.amount_paisa,
            currency=data.currency,
            fee_paisa=data.fee_paisa,
            occurred_at=data.occurred_at,
            payload_hash=payload,
            evidence_hash=evidence.evidence_hash,
        )
        .on_conflict_do_nothing(
            index_elements=[PaymentEvent.provider, PaymentEvent.external_event_id]
        )
    )
    event = db.scalars(
        select(PaymentEvent).where(
            PaymentEvent.provider == evidence.provider,
            PaymentEvent.external_event_id == data.event_id,
        )
    ).one()
    credits.same(event.payload_hash, payload)
    if order.state in {"REFUNDED", "CHARGEBACK"}:
        return order
    if data.status in {"REFUNDED", "CHARGEBACK"}:
        reverse_payment(db, order, wallet, event)
    elif data.status == "SUCCEEDED" and order.grant_id is None:
        user = db.get(User, order.user_id)
        assert user is not None
        # Late delivery of a payment made before expiry is accepted. Payment made
        # after expiry needs a reasoned staff query, never a browser override.
        if (data.occurred_at > order.expires_at and not accept_late) or (
            user.status != "active" or not user.verified
        ):
            order.state = "REVIEW"
        else:
            grant_payment(db, order, wallet)
    elif order.state == "OPEN" and order.expires_at <= now:
        order.state = "EXPIRED"
    db.flush()
    return order


def grant_payment(db: Session, order: BillingOrder, wallet: Wallet) -> None:
    now = utcnow()
    end = db.scalar(
        select(func.max(Entitlement.ends_at))
        .join(PlanPrice)
        .join(Plan)
        .where(
            Entitlement.user_id == order.user_id,
            Plan.kind == "plan",
            Entitlement.ends_at > now,
            ~Entitlement.id.in_(select(EntitlementRevocation.entitlement_id)),
        )
    )
    start = max(now, end) if end and order.valid_days else now
    grant = credits.entry(
        db,
        wallet,
        "GRANT",
        "payment:" + str(order.id),
        credits.fingerprint([str(order.id), order.amount_paisa, order.currency, order.credits]),
        order.credits,
        reason="Verified prepaid payment",
    )
    entitlement = Entitlement(
        user_id=order.user_id,
        price_version_id=order.price_version_id,
        starts_at=start,
        ends_at=start + timedelta(days=order.valid_days) if order.valid_days else None,
        operation_key="payment:" + str(order.id),
        payload_hash=credits.fingerprint([str(order.id)]),
        # Existing entitlement schema requires an actor, not necessarily staff.
        # The customer is the purchaser; staff award service is deliberately unused.
        actor_id=order.user_id,
        reason="Verified prepaid payment",
    )
    db.add(entitlement)
    db.flush()
    order.grant_id, order.entitlement_id = grant.id, entitlement.id
    order.state, order.paid_at = "PAID", now


def reverse_payment(db: Session, order: BillingOrder, wallet: Wallet, event: PaymentEvent) -> None:
    recovered, debt, transaction = 0, 0, None
    if order.grant_id:
        # Allow existing audited credit refunds without clawing back twice.
        prior = (
            db.scalar(
                select(func.coalesce(func.sum(-CreditTransaction.available_delta), 0)).where(
                    CreditTransaction.original_id == order.grant_id,
                    CreditTransaction.operation == "REFUND",
                )
            )
            or 0
        )
        remaining = max(0, order.credits - prior)
        recovered = min(wallet.available, remaining)
        debt = remaining - recovered
        if recovered:
            transaction = credits.entry(
                db,
                wallet,
                "REFUND",
                "payment-reversal:" + str(order.id),
                credits.fingerprint([str(order.id), str(event.id), recovered]),
                -recovered,
                original_id=order.grant_id,
                reason="Verified full payment reversal",
            )
        if debt:
            user = db.get(User, order.user_id)
            assert user is not None
            user.status = "disabled"
    reversal = BillingRefund(
        order_id=order.id,
        event_id=event.id,
        kind=event.status,
        amount_paisa=order.amount_paisa,
        recovered_credits=recovered,
        unrecovered_credits=debt,
        transaction_id=transaction.id if transaction else None,
    )
    db.add(reversal)
    db.flush()
    if order.entitlement_id:
        db.add(EntitlementRevocation(entitlement_id=order.entitlement_id, refund_id=reversal.id))
    order.state = event.status
    request = db.scalar(select(RefundRequest).where(RefundRequest.order_id == order.id))
    if request:
        request.state = "CONFIRMED"


def begin_refund(
    db: Session, order_id: UUID, actor_id: UUID, reason: str, key: str
) -> tuple[RefundRequest, bool]:
    credits.staff(db, actor_id, reason)
    order, _ = lock_order(db, order_id)
    payload = credits.fingerprint([str(actor_id), reason])
    old = db.scalar(select(RefundRequest).where(RefundRequest.order_id == order_id))
    if old:
        if old.operation_key == key:
            credits.same(old.payload_hash, payload)
            return old, False
        credits.fail("refund_already_requested", "Reconcile the existing refund request.")
    if order.state != "PAID":
        credits.fail("order_not_paid", "Only a paid order can request a refund.")
    row = RefundRequest(
        order_id=order_id,
        actor_id=actor_id,
        reason=reason,
        operation_key=key,
        payload_hash=payload,
    )
    db.add(row)
    db.flush()
    credits.audit(db, actor_id, "billing.refund_requested", row.id)
    return row, True


def reconcile_order(
    db: Session,
    order_id: UUID,
    actor_id: UUID,
    reason: str,
    key: str,
    evidence: VerifiedNotification | None,
    *,
    accept_late: bool = False,
) -> BillingOrder:
    credits.staff(db, actor_id, reason)
    order, _ = lock_order(db, order_id)
    payload = credits.fingerprint([str(actor_id), reason, accept_late])
    old = db.scalar(
        select(StaffPaymentAction).where(
            StaffPaymentAction.order_id == order_id, StaffPaymentAction.operation_key == key
        )
    )
    if old:
        credits.same(old.payload_hash, payload)
        return order
    if evidence:
        if evidence.notification.order_id != order_id:
            credits.fail("payment_mismatch", "Provider query returned another order.")
        order = apply_event(db, evidence, accept_late=accept_late)
    db.add(
        StaffPaymentAction(
            order_id=order_id,
            actor_id=actor_id,
            reason=reason,
            operation_key=key,
            payload_hash=payload,
            result_state=order.state,
        )
    )
    credits.audit(db, actor_id, "billing.reconciled", order_id)
    db.flush()
    return order
