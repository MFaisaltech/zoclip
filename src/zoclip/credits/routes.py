from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import select

from zoclip.auth.dependencies import DB, AdminUser, CsrfSession, CurrentUser
from zoclip.auth.service import audit
from zoclip.billing.models import EntitlementRevocation
from zoclip.core.db import utcnow
from zoclip.core.rate_limit import rate_limit
from zoclip.credits import service
from zoclip.credits.models import (
    CostPolicy,
    CreditTransaction,
    Entitlement,
    Plan,
    PlanPrice,
    ProviderUsage,
    SpendAttempt,
    SystemLimits,
)
from zoclip.credits.schemas import (
    AdjustmentInput,
    BudgetLimits,
    EntitlementInput,
    EntitlementView,
    Key,
    PlanVersionInput,
    PlanView,
    PolicyInput,
    PolicyView,
    PriceView,
    QuoteInput,
    QuoteView,
    RateInput,
    RateView,
    TransactionPage,
    TransactionView,
    UsageView,
    WalletView,
)

router = APIRouter(prefix="/api/v1", tags=["credits"])
OperationKey = Annotated[Key, Header(alias="Idempotency-Key")]


@router.get("/plans", response_model=list[PlanView], tags=["plans"])
def plans(db: DB) -> list[PlanView]:
    result = []
    for plan in db.scalars(select(Plan).order_by(Plan.slug)):
        price = db.scalar(
            select(PlanPrice)
            .where(PlanPrice.plan_id == plan.id)
            .order_by(PlanPrice.created_at.desc(), PlanPrice.id.desc())
            .limit(1)
        )
        result.append(
            PlanView(
                id=plan.id,
                slug=plan.slug,
                kind=plan.kind,
                enabled=plan.enabled,
                price=PriceView.model_validate(price) if price else None,
            )
        )
    return result


@router.get("/me/credits", response_model=WalletView)
def balance(db: DB, user: CurrentUser) -> WalletView:
    wallet = service.lock_wallet(db, user.id)
    result = WalletView(available_credits=wallet.available, reserved_credits=wallet.reserved)
    db.commit()
    return result


@router.get("/me/credit-transactions", response_model=TransactionPage)
def transactions(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> TransactionPage:
    query = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.id)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(CreditTransaction.id > cursor)
    rows = list(db.scalars(query))
    return TransactionPage(
        items=[TransactionView.model_validate(r) for r in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/me/entitlements", response_model=list[EntitlementView])
def entitlements(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> list[EntitlementView]:
    query = (
        select(Entitlement)
        .where(Entitlement.user_id == user.id)
        .order_by(Entitlement.id)
        .limit(limit)
    )
    if cursor:
        query = query.where(Entitlement.id > cursor)
    now = utcnow()
    return [
        EntitlementView(
            id=r.id,
            price_version_id=r.price_version_id,
            starts_at=r.starts_at,
            ends_at=r.ends_at,
            active=r.starts_at <= now
            and (r.ends_at is None or r.ends_at > now)
            and not db.scalar(
                select(EntitlementRevocation.id).where(EntitlementRevocation.entitlement_id == r.id)
            ),
        )
        for r in db.scalars(query)
    ]


@router.post("/jobs/quote", response_model=QuoteView)
def quote(
    data: QuoteInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> QuoteView:
    rate_limit(request, "credit-quote", str(user.id))
    row = service.make_quote(
        db, user.id, data, key, production=request.app.state.settings.app_env == "production"
    )
    result = QuoteView.model_validate(row)
    db.commit()
    return result


@router.post("/admin/plans/{plan_id}/versions", response_model=PriceView, tags=["admin"])
def plan_version(
    plan_id: UUID,
    data: PlanVersionInput,
    key: OperationKey,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> PriceView:
    row = service.configure_plan(db, plan_id, data, key, user.id)
    result = PriceView.model_validate(row)
    db.commit()
    return result


@router.post(
    "/admin/users/{user_id}/credit-adjustments", response_model=TransactionView, tags=["admin"]
)
def adjustment(
    user_id: UUID,
    data: AdjustmentInput,
    key: OperationKey,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> TransactionView:
    row = service.adjust(db, user_id, data.amount, key, user.id, data.reason)
    result = TransactionView.model_validate(row)
    db.commit()
    return result


@router.post("/admin/users/{user_id}/entitlements", response_model=EntitlementView, tags=["admin"])
def entitlement(
    user_id: UUID,
    data: EntitlementInput,
    key: OperationKey,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> EntitlementView:
    row = service.grant_entitlement(db, user_id, data.price_version_id, key, user.id, data.reason)
    now = utcnow()
    result = EntitlementView(
        id=row.id,
        price_version_id=row.price_version_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        active=row.starts_at <= now and (row.ends_at is None or row.ends_at > now),
    )
    db.commit()
    return result


@router.post("/admin/cost-rates", response_model=RateView, tags=["admin"])
def rate(
    data: RateInput, key: OperationKey, db: DB, user: AdminUser, csrf: CsrfSession
) -> RateView:
    row = service.configure_rate(db, data, key, user.id)
    result = RateView.model_validate(row)
    db.commit()
    return result


@router.post("/admin/limits/versions", response_model=PolicyView, tags=["admin"])
def policy(
    data: PolicyInput, key: OperationKey, db: DB, user: AdminUser, csrf: CsrfSession
) -> PolicyView:
    row = service.configure_policy(db, data, key, user.id)
    system = db.get(SystemLimits, 1)
    assert system is not None
    result = PolicyView(
        id=row.id, limits=BudgetLimits.model_validate(row.limits), breaker=system.breaker
    )
    db.commit()
    return result


@router.get("/admin/limits", response_model=PolicyView | None, tags=["admin"])
def current_limits(request: Request, db: DB, user: AdminUser) -> PolicyView | None:
    system = db.get(SystemLimits, 1)
    policy = db.get(CostPolicy, system.policy_id) if system and system.policy_id else None
    audit(db, request, "costs.limits_read", actor=user.id)
    result = (
        PolicyView(
            id=policy.id, limits=BudgetLimits.model_validate(policy.limits), breaker=system.breaker
        )
        if policy and system
        else None
    )
    db.commit()
    return result


@router.get("/admin/usage-costs", response_model=UsageView, tags=["admin"])
def usage(request: Request, db: DB, user: AdminUser) -> UsageView:
    rows = list(db.scalars(select(SpendAttempt)))
    actual = sum((r.actual_usd for r in db.scalars(select(ProviderUsage))), Decimal(0))
    result = UsageView(
        estimated_usd=sum((r.estimated_usd for r in rows), Decimal(0)),
        actual_usd=actual,
        held_or_unknown_usd=sum(
            (r.estimated_usd for r in rows if r.state in {"HELD", "UNKNOWN"}), Decimal(0)
        ),
        attempts=len(rows),
    )
    audit(db, request, "costs.usage_read", actor=user.id)
    db.commit()
    return result
