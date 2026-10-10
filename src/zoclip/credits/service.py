"""All methods participate in the caller's transaction; none commit or enqueue.

Lock order: target user -> wallet -> system limits. A caller must roll back on any
exception. Network/compute work must happen AFTER commit, using a fresh admission.
"""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from zoclip.auth.models import AuditLog, User
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits.models import (
    CostPolicy,
    CostRate,
    CreditReservation,
    CreditTransaction,
    Entitlement,
    Plan,
    PlanPrice,
    ProviderUsage,
    Quote,
    SpendAttempt,
    SystemLimits,
    Wallet,
)
from zoclip.credits.schemas import (
    BudgetLimits,
    ConsumptionRules,
    PlanVersionInput,
    PolicyInput,
    QuoteInput,
    RateInput,
)

ZERO = Decimal("0")


def fail(code: str, detail: str, status: int = 409) -> NoReturn:
    raise ApiError(status, code, detail)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def same(actual: str, expected: str) -> None:
    if actual != expected:
        fail("idempotency_conflict", "This operation key has a different request payload.")


def staff(db: Session, actor_id: UUID, reason: str) -> None:
    actor = db.get(User, actor_id, populate_existing=True)
    if not actor or actor.role != "admin" or actor.status != "active" or not actor.verified:
        fail("forbidden", "Staff permission required.", 403)
    if not 5 <= len(reason.strip()) <= 500:
        fail("reason_required", "A meaningful audit reason is required.", 422)


def audit(db: Session, actor_id: UUID, action: str, target_id: UUID) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_id=target_id,
            request_id=db.info.get("request_id", str(target_id)),
        )
    )


def lock_wallet(db: Session, user_id: UUID, *, active_required: bool = True) -> Wallet:
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or (active_required and (user.status != "active" or not user.verified)):
        fail("account_unavailable", "A verified active account is required.", 403)
    db.execute(
        insert(Wallet)
        .values(user_id=user_id, available=0, reserved=0)
        .on_conflict_do_nothing(index_elements=[Wallet.user_id])
    )
    wallet = db.scalars(
        select(Wallet)
        .where(Wallet.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    reconcile(db, wallet)
    return wallet


def reconcile(db: Session, wallet: Wallet) -> None:
    db.flush()
    a, r = db.execute(
        select(
            func.coalesce(func.sum(CreditTransaction.available_delta), 0),
            func.coalesce(func.sum(CreditTransaction.reserved_delta), 0),
        ).where(CreditTransaction.user_id == wallet.user_id)
    ).one()
    held = db.scalar(
        select(func.coalesce(func.sum(CreditReservation.credits), 0)).where(
            CreditReservation.user_id == wallet.user_id, CreditReservation.state == "HELD"
        )
    )
    if (wallet.available, wallet.reserved) != (a, r) or wallet.reserved != held:
        fail("accounting_mismatch", "Financial reconciliation required.", 503)


def previous(db: Session, user_id: UUID, key: str, payload: str) -> CreditTransaction | None:
    row = db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.user_id == user_id, CreditTransaction.operation_key == key
        )
    )
    if row:
        same(row.payload_hash, payload)
    return row


def entry(
    db: Session,
    wallet: Wallet,
    operation: str,
    key: str,
    payload: str,
    a: int,
    r: int = 0,
    reservation_id: UUID | None = None,
    original_id: UUID | None = None,
    actor_id: UUID | None = None,
    reason: str | None = None,
) -> CreditTransaction:
    if wallet.available + a < 0 or wallet.reserved + r < 0:
        fail("insufficient_credits", "Insufficient spendable credits.")
    wallet.available += a
    wallet.reserved += r
    row = CreditTransaction(
        user_id=wallet.user_id,
        operation=operation,
        operation_key=key,
        payload_hash=payload,
        available_delta=a,
        reserved_delta=r,
        available_after=wallet.available,
        reserved_after=wallet.reserved,
        reservation_id=reservation_id,
        original_id=original_id,
        actor_id=actor_id,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def adjust(
    db: Session,
    user_id: UUID,
    amount: int,
    key: str,
    actor_id: UUID,
    reason: str,
    *,
    grant: bool = False,
) -> CreditTransaction:
    """Explicit audited staff grant/adjustment; not payment evidence."""
    staff(db, actor_id, reason)
    if type(amount) is not int or amount == 0 or abs(amount) > 10**12 or (grant and amount < 0):
        fail("invalid_amount", "Invalid integer credit amount.", 422)
    wallet = lock_wallet(db, user_id)
    operation = "GRANT" if grant else "ADMIN_ADJUST"
    payload = fingerprint([operation, amount, str(actor_id), reason])
    old = previous(db, user_id, key, payload)
    if old:
        return old
    row = entry(db, wallet, operation, key, payload, amount, actor_id=actor_id, reason=reason)
    audit(db, actor_id, "credits." + operation.lower(), row.id)
    return row


def active_price(db: Session, user_id: UUID) -> PlanPrice:
    now = utcnow()
    entitlement = db.scalar(
        select(Entitlement)
        .join(PlanPrice)
        .join(Plan)
        .where(
            Entitlement.user_id == user_id,
            Entitlement.starts_at <= now,
            Plan.kind == "plan",
            (Entitlement.ends_at.is_(None) | (Entitlement.ends_at > now)),
        )
        .order_by((Plan.slug != "free").desc(), Entitlement.starts_at.desc(), Entitlement.id.desc())
        .limit(1)
    )
    if entitlement:
        price = db.get(PlanPrice, entitlement.price_version_id)
    else:
        price = db.scalar(
            select(PlanPrice)
            .join(Plan)
            .where(Plan.slug == "free", Plan.enabled)
            .order_by(PlanPrice.created_at.desc(), PlanPrice.id.desc())
            .limit(1)
        )
    if price is None:
        fail("plan_unconfigured", "No current plan allowance is configured.", 503)
    assert price is not None
    plan = db.get(Plan, price.plan_id)
    if not plan or not plan.enabled:
        fail("plan_unavailable", "This plan is disabled.", 503)
    return price


def configure_plan(
    db: Session, plan_id: UUID, data: PlanVersionInput, key: str, actor_id: UUID
) -> PlanPrice:
    staff(db, actor_id, data.reason)
    plan = db.scalar(select(Plan).where(Plan.id == plan_id).with_for_update())
    if not plan:
        fail("not_found", "Plan not found.", 404)
    payload = fingerprint(data.model_dump(mode="json"))
    old = db.scalar(
        select(PlanPrice).where(PlanPrice.plan_id == plan_id, PlanPrice.operation_key == key)
    )
    if old:
        same(old.payload_hash, payload)
        return old
    assert plan is not None
    if (plan.slug == "free" or plan.kind == "topup") and data.valid_days != 0:
        fail("invalid_validity", "Free plans and top-ups have no timed access.", 422)
    if plan.kind == "plan" and plan.slug != "free" and data.valid_days != 30:
        fail("invalid_validity", "Paid plan access is prepaid for 30 days.", 422)
    if plan.slug == "free" and data.price_paisa != 0:
        fail("invalid_price", "Free plan price must be zero.", 422)
    row = PlanPrice(
        plan_id=plan_id,
        operation_key=key,
        payload_hash=payload,
        price_paisa=data.price_paisa,
        included_credits=data.included_credits,
        valid_days=data.valid_days,
        approved=data.approved,
        rules=data.rules.model_dump(mode="json"),
        actor_id=actor_id,
        reason=data.reason,
    )
    db.add(row)
    db.flush()
    audit(db, actor_id, "plans.version_created", row.id)
    return row


def grant_entitlement(
    db: Session, user_id: UUID, price_id: UUID, key: str, actor_id: UUID, reason: str
) -> Entitlement:
    """Manual staff award, not an order/payment endpoint. Exactly one allowance."""
    staff(db, actor_id, reason)
    wallet = lock_wallet(db, user_id)
    payload = fingerprint([str(price_id), str(actor_id), reason])
    old = db.scalar(
        select(Entitlement).where(Entitlement.user_id == user_id, Entitlement.operation_key == key)
    )
    if old:
        same(old.payload_hash, payload)
        return old
    price = db.get(PlanPrice, price_id)
    plan = db.get(Plan, price.plan_id) if price else None
    if not price or not plan or not plan.enabled:
        fail("not_found", "Plan version not found or disabled.", 404)
    assert price is not None and plan is not None
    # Free allowances may only be awarded once, including across version changes.
    if plan.slug == "free":
        exists = db.scalar(
            select(Entitlement.id)
            .join(PlanPrice)
            .where(Entitlement.user_id == user_id, PlanPrice.plan_id == plan.id)
            .limit(1)
        )
        if exists:
            fail("allowance_already_granted", "Free allowance was already awarded.")
    now = utcnow()
    # Sequential prepaid periods avoid losing unexpired access on early renewal.
    end = db.scalar(
        select(func.max(Entitlement.ends_at))
        .join(PlanPrice)
        .join(Plan)
        .where(Entitlement.user_id == user_id, Plan.kind == "plan", Entitlement.ends_at > now)
    )
    start = max(now, end) if end and price.valid_days else now
    row = Entitlement(
        user_id=user_id,
        price_version_id=price_id,
        starts_at=start,
        ends_at=start + timedelta(days=price.valid_days) if price.valid_days else None,
        operation_key=key,
        payload_hash=payload,
        actor_id=actor_id,
        reason=reason,
    )
    db.add(row)
    db.flush()
    if price.included_credits:
        allowance_key = "allowance:" + str(row.id)
        entry(
            db,
            wallet,
            "GRANT",
            allowance_key,
            fingerprint([str(row.id)]),
            price.included_credits,
            actor_id=actor_id,
            reason=reason,
        )
    audit(db, actor_id, "plans.allowance_granted", row.id)
    return row


def calculate(data: QuoteInput, rules: ConsumptionRules) -> int:
    if (
        data.source_seconds > rules.max_source_seconds
        or data.output_count > rules.max_outputs
        or data.edit_count > rules.max_edits
    ):
        fail("plan_limit", "Requested duration, output or edit count exceeds plan limits.")
    return (
        ((data.source_seconds + 59) // 60) * rules.credits_per_minute
        + data.output_count * rules.credits_per_output
        + data.edit_count * rules.credits_per_edit
        + (rules.captions_credits if data.captions else 0)
        + (rules.reframe_credits if data.reframe else 0)
    )


def make_quote(
    db: Session, user_id: UUID, data: QuoteInput, key: str, *, production: bool = False
) -> Quote:
    lock_wallet(db, user_id)
    payload = fingerprint(data.model_dump(mode="json"))
    old = db.scalar(select(Quote).where(Quote.user_id == user_id, Quote.operation_key == key))
    if old:
        same(old.payload_hash, payload)
        return old
    price = active_price(db, user_id)
    if production and not price.approved:
        fail("price_unapproved", "Commercial pricing is not approved.", 503)
    row = Quote(
        user_id=user_id,
        price_version_id=price.id,
        operation_key=key,
        payload_hash=payload,
        request=data.model_dump(mode="json"),
        credits=calculate(data, ConsumptionRules.model_validate(price.rules)),
        expires_at=utcnow() + timedelta(minutes=15),
    )
    db.add(row)
    db.flush()
    return row


def locked_limits(db: Session) -> tuple[SystemLimits, CostPolicy, BudgetLimits]:
    row = db.scalars(
        select(SystemLimits)
        .where(SystemLimits.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    policy = db.get(CostPolicy, row.policy_id) if row.policy_id else None
    if row.breaker or not policy:
        fail("spending_disabled", "Expense policy is missing or circuit breaker is open.", 503)
    assert policy is not None
    return row, policy, BudgetLimits.model_validate(policy.limits)


def configured_rates(db: Session, limits: BudgetLimits) -> dict[str, CostRate]:
    rates = list(db.scalars(select(CostRate).where(CostRate.id.in_(limits.rate_ids))))
    result = {r.component: r for r in rates}
    if len(rates) != len(limits.rate_ids) or len(result) != len(rates):
        fail("rates_unconfigured", "Missing or ambiguous expense rates.", 503)
    expected = {
        "deepgram": "minute",
        "gemini_input": "token",
        "gemini_output": "token",
        "render": "cpu_second",
        "storage": "gb_day",
    }
    if set(result) != set(expected) or any(result[k].unit != v for k, v in expected.items()):
        fail(
            "rates_unconfigured", "All expense components require correctly dimensioned rates.", 503
        )
    return result


def estimate(db: Session, data: QuoteInput, limits: BudgetLimits) -> Decimal:
    rates = configured_rates(db, limits)
    quantities = {
        "deepgram": ("minute", (data.source_seconds + 59) // 60),
        "gemini_input": ("token", data.source_seconds * limits.input_tokens_per_second),
        "gemini_output": ("token", limits.max_output_tokens),
        "render": (
            "cpu_second",
            (data.output_count + data.edit_count) * limits.render_cpu_seconds_per_output,
        ),
        "storage": ("gb_day", data.output_count * limits.storage_gb_days_per_output),
    }
    cost = ZERO
    for component, (unit, units) in quantities.items():
        rate = rates.get(component)
        if not rate or rate.unit != unit or units > rate.max_units:
            fail("rates_unconfigured", "A bounded rate for every expense is required.", 503)
        cost += rate.unit_usd * units
    return cost


def check_budgets(
    db: Session,
    limits: BudgetLimits,
    user_id: UUID,
    reservation_id: UUID | None,
    additional: Decimal,
) -> None:
    """SystemLimits lock serializes all check-and-hold operations, including users.

    All unresolved exposure counts in each current period, even across midnight.
    Completed actual costs count by admission time and recording time, conservatively.
    """
    now = utcnow()
    day, month = (
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    )
    unresolved = SpendAttempt.state.in_(["HELD", "UNKNOWN"])
    checks: list[tuple[Decimal, datetime | None, Any]] = [
        (limits.global_daily_usd, day, None),
        (limits.global_monthly_usd, month, None),
        (limits.user_daily_usd, day, SpendAttempt.user_id == user_id),
        (limits.user_monthly_usd, month, SpendAttempt.user_id == user_id),
    ]
    if reservation_id:
        checks.append((limits.per_job_usd, None, SpendAttempt.reservation_id == reservation_id))
    exposure = case(
        (unresolved, SpendAttempt.estimated_usd), else_=func.coalesce(ProviderUsage.actual_usd, 0)
    )
    for maximum, boundary, scope in checks:
        query = (
            select(func.coalesce(func.sum(exposure), 0))
            .select_from(SpendAttempt)
            .outerjoin(ProviderUsage, ProviderUsage.attempt_id == SpendAttempt.id)
        )
        if scope is not None:
            query = query.where(scope)
        if boundary is not None:
            query = query.where(
                or_(
                    unresolved,
                    SpendAttempt.created_at >= boundary,
                    ProviderUsage.created_at >= boundary,
                )
            )
        total = db.scalar(query) or ZERO
        if total + additional > maximum:
            fail("budget_exceeded", "Configured expense budget is insufficient.", 503)


def reserve(
    db: Session, user_id: UUID, quote_id: UUID, job_id: UUID, key: str, *, production: bool = False
) -> CreditReservation:
    wallet = lock_wallet(db, user_id)
    payload = fingerprint(["RESERVE", str(quote_id), str(job_id)])
    old = previous(db, user_id, key, payload)
    if old:
        assert old.reservation_id is not None
        return db.scalars(
            select(CreditReservation).where(CreditReservation.id == old.reservation_id)
        ).one()
    quote = db.scalar(select(Quote).where(Quote.id == quote_id, Quote.user_id == user_id))
    if not quote:
        fail("not_found", "Quote not found.", 404)
    assert quote is not None
    if quote.expires_at <= utcnow():
        fail("quote_expired", "Request a fresh quote.")
    price = active_price(db, user_id)
    if quote.price_version_id != price.id:
        fail("quote_stale", "The current plan version changed; request a fresh quote.")
    if production and not price.approved:
        fail("price_unapproved", "Commercial pricing is not approved.", 503)
    if db.scalar(
        select(CreditReservation.id).where(
            (CreditReservation.job_id == job_id) | (CreditReservation.quote_id == quote_id)
        )
    ):
        fail("reservation_exists", "Job or quote already has a reservation.")
    rules = ConsumptionRules.model_validate(price.rules)
    if wallet.available < quote.credits:
        fail("insufficient_credits", "Insufficient spendable credits.")
    now = utcnow()
    day, month = (
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    )
    rows = list(db.scalars(select(CreditReservation).where(CreditReservation.user_id == user_id)))
    if sum(r.state == "HELD" for r in rows) >= rules.max_concurrent_jobs:
        fail("concurrency_limit", "Plan concurrent job limit reached.")
    for boundary, cap in [(day, rules.daily_credits), (month, rules.monthly_credits)]:
        used = sum(
            r.credits
            for r in rows
            if r.state == "HELD"
            or (r.state == "SETTLED" and (r.created_at >= boundary or r.updated_at >= boundary))
        )
        if used + quote.credits > cap:
            fail("usage_limit", "Plan daily or monthly allowance exceeded.")
    _, _, limits = locked_limits(db)
    count = (
        db.scalar(
            select(func.count())
            .select_from(CreditReservation)
            .where(CreditReservation.state == "HELD")
        )
        or 0
    )
    if count >= limits.max_open_reservations:
        fail("capacity_limit", "Configured outstanding reservation limit reached.", 503)
    predicted = estimate(db, QuoteInput.model_validate(quote.request), limits)
    if predicted > limits.per_job_usd:
        fail("budget_exceeded", "Estimated job expense exceeds its ceiling.", 503)
    check_budgets(db, limits, user_id, None, predicted)
    row = CreditReservation(
        user_id=user_id, quote_id=quote.id, job_id=job_id, credits=quote.credits
    )
    db.add(row)
    db.flush()
    entry(db, wallet, "RESERVE", key, payload, -row.credits, row.credits, row.id)
    return row


def finish(
    db: Session, user_id: UUID, reservation_id: UUID, key: str, *, success: bool, evidence: str
) -> CreditTransaction:
    """Trusted worker only: evidence is a durable verified output/final-failure ID.

    Phase 3/5 must atomically write job terminal state and invoke this contract.
    No customer endpoint can declare successful output or final failure.
    """
    wallet = lock_wallet(db, user_id, active_required=False)
    operation = "SETTLE" if success else "RELEASE"
    if not 1 <= len(evidence) <= 128:
        fail("evidence_required", "A durable result reference is required.", 422)
    payload = fingerprint([operation, str(reservation_id), evidence])
    old = previous(db, user_id, key, payload)
    if old:
        return old
    row = db.scalar(
        select(CreditReservation).where(
            CreditReservation.id == reservation_id, CreditReservation.user_id == user_id
        )
    )
    if not row:
        fail("not_found", "Reservation not found.", 404)
    assert row is not None
    if row.state != "HELD":
        fail("reservation_final", "Reservation already finalized.")
    row.state = "SETTLED" if success else "RELEASED"
    row.deliverable_reference = evidence
    result = entry(
        db, wallet, operation, key, payload, 0 if success else row.credits, -row.credits, row.id
    )
    reconcile(db, wallet)
    return result


def refund(
    db: Session,
    user_id: UUID,
    original_id: UUID,
    amount: int,
    key: str,
    actor_id: UUID,
    reason: str,
) -> CreditTransaction:
    """Refund a settled charge (+credits) or reverse an unspent grant (-credits).

    This is internal credit accounting, not a gateway currency refund.
    """
    staff(db, actor_id, reason)
    if type(amount) is not int or not 1 <= amount <= 10**12:
        fail("invalid_amount", "A positive integer amount is required.", 422)
    wallet = lock_wallet(db, user_id, active_required=False)
    payload = fingerprint(["REFUND", str(original_id), amount, str(actor_id), reason])
    old = previous(db, user_id, key, payload)
    if old:
        return old
    original = db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.id == original_id, CreditTransaction.user_id == user_id
        )
    )
    if not original or original.operation not in {"GRANT", "SETTLE"}:
        fail("invalid_refund", "An owned grant or settled charge is required.")
    assert original is not None
    prior = (
        db.scalar(
            select(func.coalesce(func.sum(func.abs(CreditTransaction.available_delta)), 0)).where(
                CreditTransaction.original_id == original_id,
                CreditTransaction.operation == "REFUND",
            )
        )
        or 0
    )
    maximum = (
        original.available_delta if original.operation == "GRANT" else -original.reserved_delta
    )
    if prior + amount > maximum:
        fail("refund_exceeds_original", "Refund exceeds the unrefunded original amount.")
    result = entry(
        db,
        wallet,
        "REFUND",
        key,
        payload,
        -amount if original.operation == "GRANT" else amount,
        original_id=original.id,
        actor_id=actor_id,
        reason=reason,
    )
    audit(db, actor_id, "credits.refund", result.id)
    return result


def configure_rate(db: Session, data: RateInput, key: str, actor_id: UUID) -> CostRate:
    staff(db, actor_id, data.reason)
    # Configuration and paid-call admission use the same singleton mutex.
    db.scalars(select(SystemLimits).where(SystemLimits.id == 1).with_for_update()).one()
    payload = fingerprint(data.model_dump(mode="json"))
    old = db.scalar(
        select(CostRate).where(CostRate.component == data.component, CostRate.operation_key == key)
    )
    if old:
        same(old.payload_hash, payload)
        return old
    row = CostRate(**data.model_dump(), operation_key=key, payload_hash=payload, actor_id=actor_id)
    db.add(row)
    db.flush()
    audit(db, actor_id, "costs.rate_created", row.id)
    return row


def configure_policy(db: Session, data: PolicyInput, key: str, actor_id: UUID) -> CostPolicy:
    staff(db, actor_id, data.reason)
    system = db.scalars(
        select(SystemLimits)
        .where(SystemLimits.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    payload = fingerprint(data.model_dump(mode="json"))
    old = db.scalar(select(CostPolicy).where(CostPolicy.operation_key == key))
    if old:
        same(old.payload_hash, payload)
        return old
    configured_rates(db, data.limits)
    row = CostPolicy(
        operation_key=key,
        payload_hash=payload,
        limits=data.limits.model_dump(mode="json"),
        actor_id=actor_id,
        reason=data.reason,
    )
    db.add(row)
    db.flush()
    system.policy_id, system.breaker = row.id, data.breaker
    audit(db, actor_id, "costs.policy_created", row.id)
    return row


def admit_spend(
    db: Session, user_id: UUID, reservation_id: UUID, rate_id: UUID, units: int, key: str
) -> tuple[SpendAttempt, bool]:
    """Return (attempt, fresh). Execute only after commit and ONLY when fresh.

    A replay is never permission to repeat a paid side effect. HELD after a crash
    is uncertain until checkpoint/provider evidence proves otherwise.
    """
    lock_wallet(db, user_id)
    payload = fingerprint([str(rate_id), units])
    old = db.scalar(
        select(SpendAttempt).where(
            SpendAttempt.reservation_id == reservation_id,
            SpendAttempt.operation_key == key,
            SpendAttempt.user_id == user_id,
        )
    )
    if old:
        same(old.payload_hash, payload)
        return old, False
    reservation = db.scalar(
        select(CreditReservation).where(
            CreditReservation.id == reservation_id, CreditReservation.user_id == user_id
        )
    )
    if not reservation:
        fail("not_found", "Reservation not found.", 404)
    assert reservation is not None
    if reservation.state != "HELD":
        fail("reservation_final", "Paid work requires an active credit reservation.")
    _, policy, limits = locked_limits(db)
    rates = configured_rates(db, limits)
    rate = next((r for r in rates.values() if r.id == rate_id), None)
    if not rate or type(units) is not int or not 1 <= units <= rate.max_units:
        fail("rate_limit", "Configured bounded rate and valid units required.", 503)
    if rate.component == "gemini_output" and units > limits.max_output_tokens:
        fail("rate_limit", "Configured output token ceiling exceeded.", 503)
    previous_attempts = list(
        db.scalars(select(SpendAttempt).where(SpendAttempt.reservation_id == reservation_id))
    )
    if any(a.state in {"HELD", "UNKNOWN"} for a in previous_attempts):
        fail("uncertain_spend", "Reconcile the outstanding expense before another call.", 503)
    if len(previous_attempts) >= limits.max_attempts_per_job:
        fail("attempt_limit", "Job expense attempt cap reached.", 503)
    predicted = rate.unit_usd * units
    check_budgets(db, limits, user_id, reservation_id, predicted)
    row = SpendAttempt(
        user_id=user_id,
        reservation_id=reservation_id,
        rate_id=rate_id,
        policy_id=policy.id,
        operation_key=key,
        payload_hash=payload,
        units=units,
        estimated_usd=predicted,
    )
    db.add(row)
    db.flush()
    return row, True


def admit_gemini_spend(
    db: Session,
    user_id: UUID,
    reservation_id: UUID,
    input_rate_id: UUID,
    output_rate_id: UUID,
    input_units: int,
    output_units: int,
    key: str,
) -> tuple[list[SpendAttempt], bool]:
    """Atomically admit both dimensions of ONE Gemini request, never two side effects.

    No existing HELD/UNKNOWN is bypassed. Both rows commit or neither does.
    Replays must contain the identical pair and never authorize execution.
    """
    lock_wallet(db, user_id)
    old = list(
        db.scalars(
            select(SpendAttempt).where(
                SpendAttempt.reservation_id == reservation_id,
                SpendAttempt.user_id == user_id,
                SpendAttempt.operation_key.in_([key + ":input", key + ":output"]),
            )
        )
    )
    expected = {
        key + ":input": (input_rate_id, input_units),
        key + ":output": (output_rate_id, output_units),
    }
    if old:
        if len(old) != 2:
            fail(
                "accounting_mismatch", "Incomplete provider admission requires reconciliation.", 503
            )
        for attempt in old:
            rate_id, units = expected[attempt.operation_key]
            same(attempt.payload_hash, fingerprint([str(rate_id), units]))
        return sorted(old, key=lambda a: a.operation_key), False
    _, policy, limits = locked_limits(db)
    rates = configured_rates(db, limits)
    if (rates["gemini_input"].id, rates["gemini_output"].id) != (input_rate_id, output_rate_id):
        fail("rates_unconfigured", "Gemini input/output rate pair required.", 503)
    prior = list(
        db.scalars(select(SpendAttempt).where(SpendAttempt.reservation_id == reservation_id))
    )
    if len(prior) + 2 > limits.max_attempts_per_job:
        fail("attempt_limit", "Job expense attempt cap reached.", 503)
    # Original admission checks the reservation, unknown exposure and every budget.
    first, fresh = admit_spend(
        db, user_id, reservation_id, input_rate_id, input_units, key + ":input"
    )
    assert fresh
    rate = rates["gemini_output"]
    if type(output_units) is not int or not 1 <= output_units <= min(
        rate.max_units, limits.max_output_tokens
    ):
        fail("rate_limit", "Configured output token ceiling exceeded.", 503)
    predicted = rate.unit_usd * output_units
    check_budgets(
        db, limits, user_id, reservation_id, predicted
    )  # Includes first, still uncommitted.
    second = SpendAttempt(
        user_id=user_id,
        reservation_id=reservation_id,
        rate_id=rate.id,
        policy_id=policy.id,
        operation_key=key + ":output",
        payload_hash=fingerprint([str(rate.id), output_units]),
        units=output_units,
        estimated_usd=predicted,
    )
    db.add(second)
    db.flush()
    return [first, second], True


def record_spend(
    db: Session, user_id: UUID, attempt_id: UUID, *, units: int | None, outcome: str, evidence: str
) -> SpendAttempt:
    """units=None retains unknown exposure. Zero requires proven non-billable failure.

    Overruns are recorded even when above the hold; open circuit breaker, never
    discard sunk costs to make a budget appear compliant.
    """
    lock_wallet(db, user_id, active_required=False)
    system = db.scalars(
        select(SystemLimits)
        .where(SystemLimits.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    row = db.scalar(
        select(SpendAttempt)
        .where(SpendAttempt.id == attempt_id, SpendAttempt.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if not row:
        fail("not_found", "Expense attempt not found.", 404)
    assert row is not None
    if not 1 <= len(evidence) <= 128 or outcome not in {"success", "failure", "unknown"}:
        fail("invalid_evidence", "Bounded checkpoint reference and outcome required.", 422)
    if units is None:
        if row.state in {"RECORDED", "VOID"}:
            fail("expense_final", "Expense already reconciled.")
        row.state = "UNKNOWN"
        return row
    if type(units) is not int or not 0 <= units <= 10**12 or outcome == "unknown":
        fail("invalid_usage", "Known nonnegative integer usage required.", 422)
    existing = db.scalar(select(ProviderUsage).where(ProviderUsage.attempt_id == row.id))
    if existing:
        same(
            fingerprint([existing.units, existing.outcome, existing.evidence_reference]),
            fingerprint([units, outcome, evidence]),
        )
        return row
    rate = db.get(CostRate, row.rate_id)
    assert rate is not None
    actual = rate.unit_usd * units
    db.add(
        ProviderUsage(
            attempt_id=row.id,
            units=units,
            actual_usd=actual,
            outcome=outcome,
            evidence_reference=evidence,
        )
    )
    row.state = "RECORDED" if units else "VOID"
    if actual > row.estimated_usd:
        system.breaker = True
    db.flush()
    return row
