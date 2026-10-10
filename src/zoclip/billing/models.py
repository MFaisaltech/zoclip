from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class BillingOrder(IdentityMixin, Base):
    __tablename__ = "billing_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key"),
        CheckConstraint("amount_paisa > 0 AND credits > 0", name="amounts"),
        CheckConstraint("currency = 'PKR' AND valid_days IN (0, 30)", name="terms"),
        CheckConstraint(
            "state IN ('OPEN','EXPIRED','REVIEW','PAID','REFUNDED','CHARGEBACK')", name="state"
        ),
        CheckConstraint(
            "(grant_id IS NULL) = (entitlement_id IS NULL) "
            "AND (grant_id IS NULL) = (paid_at IS NULL) "
            "AND (state <> 'PAID' OR grant_id IS NOT NULL)",
            name="paid_links",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    price_version_id: Mapped[UUID] = mapped_column(ForeignKey("plan_price_versions.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    fee_schedule_version: Mapped[str] = mapped_column(String(60))
    amount_paisa: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    credits: Mapped[int] = mapped_column(BigInteger)
    valid_days: Mapped[int]
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="OPEN")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("wallet_transactions.id"), unique=True)
    entitlement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_entitlements.id"), unique=True
    )


class PaymentAttempt(IdentityMixin, Base):
    """Immutable checkout reference. Only local deterministic sandbox creation is enabled."""

    __tablename__ = "payment_attempts"
    __table_args__ = (UniqueConstraint("provider", "reference"),)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(128))


class PaymentEvent(IdentityMixin, Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id"),
        CheckConstraint("amount_paisa > 0 AND fee_paisa >= 0", name="amounts"),
        CheckConstraint("currency = 'PKR'", name="currency"),
        CheckConstraint(
            "status IN ('PENDING','FAILED','SUCCEEDED','REFUNDED','CHARGEBACK')", name="status"
        ),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    external_event_id: Mapped[str] = mapped_column(String(128))
    reference: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20))
    amount_paisa: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    fee_paisa: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64))


class BillingRefund(IdentityMixin, Base):
    """Confirmed full reversal only; an outbound refund request is not evidence."""

    __tablename__ = "billing_refunds"
    __table_args__ = (
        CheckConstraint(
            "amount_paisa > 0 AND recovered_credits >= 0 AND unrecovered_credits >= 0",
            name="amounts",
        ),
        CheckConstraint("kind IN ('REFUNDED','CHARGEBACK')", name="kind"),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"), unique=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("payment_events.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount_paisa: Mapped[int] = mapped_column(BigInteger)
    recovered_credits: Mapped[int] = mapped_column(BigInteger)
    unrecovered_credits: Mapped[int] = mapped_column(BigInteger)
    transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wallet_transactions.id"), unique=True
    )


class EntitlementRevocation(IdentityMixin, Base):
    __tablename__ = "billing_entitlement_revocations"
    entitlement_id: Mapped[UUID] = mapped_column(ForeignKey("user_entitlements.id"), unique=True)
    refund_id: Mapped[UUID] = mapped_column(ForeignKey("billing_refunds.id"), unique=True)


class RefundRequest(IdentityMixin, Base):
    """Durable outbound intent; UNKNOWN is reconciled, never blindly retried."""

    __tablename__ = "billing_refund_requests"
    __table_args__ = (CheckConstraint("state IN ('UNKNOWN','CONFIRMED')", name="state"),)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"), unique=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(20), default="UNKNOWN")


class StaffPaymentAction(IdentityMixin, Base):
    __tablename__ = "billing_staff_actions"
    __table_args__ = (UniqueConstraint("order_id", "operation_key"),)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
    result_state: Mapped[str] = mapped_column(String(20))
