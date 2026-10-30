"""Independently verified staff purchases, using the existing atomic payment ledger."""

import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from zoclip.auth.models import User
from zoclip.billing import service
from zoclip.billing.models import BillingOrder, PaymentAttempt, PaymentEvent, StaffPaymentAction
from zoclip.billing.schemas import ManualPaymentInput, ManualRefundInput
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.credits import service as credits
from zoclip.credits.models import Plan, PlanPrice
from zoclip.credits.schemas import ConsumptionRules


def authorized(db: Session, settings: Settings, actor: UUID, reason: str) -> None:
    credits.staff(db, actor, reason)
    if not settings.manual_payments_enabled:
        credits.fail("manual_payments_disabled", "Manual purchase activation is disabled.", 503)
    if (
        settings.payment_provider != "disabled"
        or settings.enable_live_payments
        or settings.transcription_provider != "whisper"
        or settings.analysis_provider != "local"
        or settings.deepgram_api_key.get_secret_value()
        or settings.gemini_api_key.get_secret_value()
    ):
        credits.fail(
            "manual_payments_disabled", "Manual purchases require closed integrations.", 503
        )


def activate(
    db: Session, settings: Settings, actor: UUID, owner: UUID, data: ManualPaymentInput, key: str
) -> BillingOrder:
    authorized(db, settings, actor, data.reason)
    wallet = credits.lock_wallet(db, owner, active_required=False)
    order_key = "manual:" + hashlib.sha256(key.encode()).hexdigest()
    payload = credits.fingerprint([str(actor), str(owner), data.model_dump(mode="json")])
    old = db.scalar(
        select(BillingOrder).where(
            BillingOrder.user_id == owner, BillingOrder.operation_key == order_key
        )
    )
    if old:
        credits.same(old.payload_hash, payload)
        return old  # Includes refunded orders: replay never grants again.
    account = db.get(User, owner)
    if account is None or account.status != "active" or not account.verified:
        credits.fail("account_unavailable", "A verified active account is required.", 403)
    price = db.get(PlanPrice, data.price_version_id)
    plan = db.get(Plan, price.plan_id) if price else None
    latest = (
        db.scalar(
            select(PlanPrice.id)
            .where(PlanPrice.plan_id == plan.id)
            .order_by(PlanPrice.created_at.desc(), PlanPrice.id.desc())
            .limit(1)
        )
        if plan
        else None
    )
    if not price or not plan or not plan.enabled or plan.slug not in {"creator", "pro"}:
        credits.fail("plan_unavailable", "Select a current Creator or Pro package.")
    if (
        not price.approved
        or price.id != latest
        or not ConsumptionRules.model_validate(price.rules).purchasable
    ):
        credits.fail("price_unapproved", "Select the latest approved purchasable terms.")
    if data.amount_paisa != price.price_paisa:
        credits.fail("payment_mismatch", "Verified payment must match the package price exactly.")
    now = utcnow()
    order = BillingOrder(
        user_id=owner,
        price_version_id=price.id,
        provider="manual",
        fee_schedule_version="manual-independent-verification-v1",
        amount_paisa=price.price_paisa,
        credits=price.included_credits,
        valid_days=price.valid_days,
        operation_key=order_key,
        payload_hash=payload,
        expires_at=now + timedelta(days=1),
    )
    db.add(order)
    db.flush()
    claimed = db.scalar(
        insert(PaymentAttempt)
        .values(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            order_id=order.id,
            provider="manual",
            reference=data.payment_reference,
        )
        .on_conflict_do_nothing(index_elements=[PaymentAttempt.provider, PaymentAttempt.reference])
        .returning(PaymentAttempt.id)
    )
    if claimed is None:
        credits.fail("payment_already_used", "This payment reference has already been recorded.")
    event = PaymentEvent(
        order_id=order.id,
        provider="manual",
        external_event_id="paid:" + data.payment_reference,
        reference=data.payment_reference,
        status="SUCCEEDED",
        amount_paisa=order.amount_paisa,
        currency="PKR",
        fee_paisa=0,
        occurred_at=now,
        payload_hash=payload,
        evidence_hash=payload,
    )
    db.add(event)
    service.grant_payment(db, order, wallet)
    db.add(
        StaffPaymentAction(
            order_id=order.id,
            actor_id=actor,
            operation_key=key,
            payload_hash=payload,
            reason=data.reason,
            result_state=order.state,
        )
    )
    credits.audit(db, actor, "billing.manual_payment_verified", order.id)
    db.flush()
    return order


def refund(
    db: Session, settings: Settings, actor: UUID, order_id: UUID, data: ManualRefundInput, key: str
) -> BillingOrder:
    authorized(db, settings, actor, data.reason)
    order, wallet = service.lock_order(db, order_id)
    payload = credits.fingerprint(["manual-refund", str(actor), data.model_dump(mode="json")])
    old = db.scalar(
        select(StaffPaymentAction).where(
            StaffPaymentAction.order_id == order_id, StaffPaymentAction.operation_key == key
        )
    )
    if old:
        credits.same(old.payload_hash, payload)
        return order
    if order.provider != "manual" or order.state != "PAID":
        credits.fail("order_not_paid", "Only an unreversed manual purchase may be refunded.")
    now = utcnow()
    event_id = db.scalar(
        insert(PaymentEvent)
        .values(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            order_id=order.id,
            provider="manual",
            external_event_id="refund:" + data.payment_reference.upper(),
            reference=service.reference(db, order),
            status="REFUNDED",
            amount_paisa=order.amount_paisa,
            currency="PKR",
            fee_paisa=0,
            occurred_at=now,
            payload_hash=payload,
            evidence_hash=payload,
        )
        .on_conflict_do_nothing(
            index_elements=[PaymentEvent.provider, PaymentEvent.external_event_id]
        )
        .returning(PaymentEvent.id)
    )
    if event_id is None:
        credits.fail("payment_already_used", "This refund reference has already been recorded.")
    event = db.get(PaymentEvent, event_id)
    assert event is not None
    service.reverse_payment(db, order, wallet, event)
    db.add(
        StaffPaymentAction(
            order_id=order.id,
            actor_id=actor,
            operation_key=key,
            payload_hash=payload,
            reason=data.reason,
            result_state=order.state,
        )
    )
    credits.audit(db, actor, "billing.manual_refund_verified", order.id)
    db.flush()
    return order
