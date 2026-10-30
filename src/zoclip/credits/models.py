from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class Wallet(IdentityMixin, Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("available >= 0 AND reserved >= 0", name="nonnegative"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    available: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)


class Plan(IdentityMixin, Base):
    __tablename__ = "plans"
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (CheckConstraint("kind IN ('plan', 'topup')", name="kind"),)


class PlanPrice(IdentityMixin, Base):
    __tablename__ = "plan_price_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "operation_key"),
        CheckConstraint("price_paisa >= 0 AND included_credits >= 0", name="nonnegative"),
        CheckConstraint("valid_days IN (0, 30)", name="validity"),
    )
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    price_paisa: Mapped[int] = mapped_column(BigInteger)
    included_credits: Mapped[int] = mapped_column(BigInteger)
    valid_days: Mapped[int]
    approved: Mapped[bool] = mapped_column(default=False)
    rules: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))


class Entitlement(IdentityMixin, Base):
    __tablename__ = "user_entitlements"
    __table_args__ = (UniqueConstraint("user_id", "operation_key"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    price_version_id: Mapped[UUID] = mapped_column(ForeignKey("plan_price_versions.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))


class CreditExpiryEvent(IdentityMixin, Base):
    """Append-only record that the expiry sweep processed an entitlement.

    user_entitlements is immutable, so the sweep cannot stamp the row it
    processed; it records the processing (and any deduction) here instead,
    mirroring the billing entitlement-revocations pattern.
    """

    __tablename__ = "credit_expiry_events"
    __table_args__ = (CheckConstraint("deducted_credits >= 0", name="nonnegative"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    entitlement_id: Mapped[UUID] = mapped_column(ForeignKey("user_entitlements.id"), unique=True)
    deducted_credits: Mapped[int] = mapped_column(BigInteger, default=0)


class Quote(IdentityMixin, Base):
    __tablename__ = "credit_quotes"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key"),
        CheckConstraint("credits > 0", name="positive"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    price_version_id: Mapped[UUID] = mapped_column(ForeignKey("plan_price_versions.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    credits: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CreditReservation(IdentityMixin, Base):
    __tablename__ = "credit_reservations"
    __table_args__ = (
        CheckConstraint("credits > 0", name="positive"),
        CheckConstraint("state IN ('HELD', 'SETTLED', 'RELEASED')", name="state"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    quote_id: Mapped[UUID] = mapped_column(ForeignKey("credit_quotes.id"), unique=True)
    job_id: Mapped[UUID] = mapped_column(unique=True)
    credits: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20), default="HELD")
    deliverable_reference: Mapped[str | None] = mapped_column(String(128))


class CreditTransaction(IdentityMixin, Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key"),
        CheckConstraint("available_after >= 0 AND reserved_after >= 0", name="nonnegative"),
        CheckConstraint(
            "(operation = 'GRANT' AND available_delta > 0 AND reserved_delta = 0) OR "
            "(operation = 'RESERVE' AND available_delta < 0 "
            "AND reserved_delta = -available_delta) OR "
            "(operation = 'SETTLE' AND available_delta = 0 AND reserved_delta < 0) OR "
            "(operation = 'RELEASE' AND available_delta > 0 "
            "AND reserved_delta = -available_delta) OR "
            "(operation IN ('REFUND', 'ADMIN_ADJUST') "
            "AND available_delta != 0 AND reserved_delta = 0) OR "
            "(operation = 'EXPIRE' AND available_delta < 0 AND reserved_delta = 0)",
            name="operation_deltas",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[str] = mapped_column(String(20))
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    available_delta: Mapped[int] = mapped_column(BigInteger)
    reserved_delta: Mapped[int] = mapped_column(BigInteger)
    available_after: Mapped[int] = mapped_column(BigInteger)
    reserved_after: Mapped[int] = mapped_column(BigInteger)
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credit_reservations.id"), index=True
    )
    original_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wallet_transactions.id"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))


class CostRate(IdentityMixin, Base):
    __tablename__ = "cost_rate_versions"
    __table_args__ = (
        UniqueConstraint("component", "operation_key"),
        CheckConstraint("unit_usd > 0 AND max_units > 0", name="amounts"),
    )
    component: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(30))
    unit_usd: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    max_units: Mapped[int] = mapped_column(BigInteger)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))


class CostPolicy(IdentityMixin, Base):
    __tablename__ = "cost_policy_versions"
    operation_key: Mapped[str] = mapped_column(String(128), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    limits: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))


class SystemLimits(Base):
    __tablename__ = "system_limits"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cost_policy_versions.id"), index=True
    )
    breaker: Mapped[bool] = mapped_column(default=True)


class SpendAttempt(IdentityMixin, Base):
    __tablename__ = "spend_attempts"
    __table_args__ = (
        UniqueConstraint("reservation_id", "operation_key"),
        CheckConstraint("estimated_usd >= 0", name="nonnegative"),
        CheckConstraint("state IN ('HELD', 'UNKNOWN', 'RECORDED', 'VOID')", name="state"),
        CheckConstraint("units > 0", name="units"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("credit_reservations.id"), index=True)
    rate_id: Mapped[UUID] = mapped_column(ForeignKey("cost_rate_versions.id"), index=True)
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("cost_policy_versions.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    units: Mapped[int] = mapped_column(BigInteger)
    estimated_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    state: Mapped[str] = mapped_column(String(20), default="HELD")


class ProviderUsage(IdentityMixin, Base):
    __tablename__ = "provider_usage"
    __table_args__ = (CheckConstraint("actual_usd >= 0 AND units >= 0", name="nonnegative"),)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("spend_attempts.id"), unique=True)
    units: Mapped[int] = mapped_column(BigInteger)
    actual_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    outcome: Mapped[str] = mapped_column(String(30))
    evidence_reference: Mapped[str] = mapped_column(String(128))
