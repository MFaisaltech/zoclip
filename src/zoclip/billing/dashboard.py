"""Owner-scoped billing visibility and bounded staff reads; no financial mutations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from zoclip.auth.dependencies import DB, AdminUser, CurrentUser
from zoclip.auth.models import User
from zoclip.billing.models import EntitlementRevocation
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service
from zoclip.credits.models import CreditReservation, Entitlement, Plan, Wallet
from zoclip.credits.schemas import PlanView, PriceView, StrictModel
from zoclip.media.models import Job
from zoclip.media.schemas import JobView

router = APIRouter(prefix="/api/v1", tags=["billing-dashboard"])


class BillingOverview(StrictModel):
    plan: PlanView | None
    access_source: Literal["entitlement", "free_default", "unconfigured"]
    access_ends_at: datetime | None
    day_starts_at: datetime
    month_starts_at: datetime
    daily_used_credits: int
    monthly_used_credits: int
    held_credits: int
    held_reservations: int
    settled_credits: int
    released_credits: int
    checkout_available: Literal[False] = False
    checkout_reason: Literal["Merchant checkout is not available. No purchase will be created."] = (
        "Merchant checkout is not available. No purchase will be created."
    )
    auto_renews: Literal[False] = False


class ReservationView(StrictModel):
    id: UUID
    job_id: UUID
    credits: int
    state: str
    created_at: datetime
    updated_at: datetime


class ReservationPage(StrictModel):
    items: list[ReservationView]
    next_cursor: UUID | None


class CustomerView(StrictModel):
    id: UUID
    email: str
    status: str
    verified: bool
    created_at: datetime
    available_credits: int
    reserved_credits: int


class CustomerPage(StrictModel):
    items: list[CustomerView]
    next_cursor: UUID | None


class StaffJob(StrictModel):
    user_id: UUID
    job: JobView


class StaffJobPage(StrictModel):
    items: list[StaffJob]
    next_cursor: UUID | None


class AdminOverview(StrictModel):
    customers: int
    verified_customers: int
    available_credits: int
    reserved_credits: int
    active_prepaid_access: int
    job_states: dict[str, int]
    spending_blocked: bool
    checkout_available: Literal[False] = False


def overview(db: Session, user_id: UUID) -> BillingOverview:
    now = utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    scope = CreditReservation.user_id == user_id

    def used(boundary: datetime) -> int:
        # Match reserve() exactly: all in-flight holds, plus activity in this UTC period.
        return int(
            db.scalar(
                select(func.coalesce(func.sum(CreditReservation.credits), 0)).where(
                    scope,
                    or_(
                        CreditReservation.state == "HELD",
                        and_(
                            CreditReservation.state == "SETTLED",
                            or_(
                                CreditReservation.created_at >= boundary,
                                CreditReservation.updated_at >= boundary,
                            ),
                        ),
                    ),
                )
            )
            or 0
        )

    states = {
        state: (int(count), int(credits))
        for state, count, credits in db.execute(
            select(CreditReservation.state, func.count(), func.sum(CreditReservation.credits))
            .where(scope)
            .group_by(CreditReservation.state)
        )
    }
    plan = None
    entitlement = None
    try:
        price = service.active_price(db, user_id)
    except ApiError as exc:
        if exc.code not in {"plan_unconfigured", "plan_unavailable"}:
            raise
    else:
        catalog = db.get(Plan, price.plan_id)
        assert catalog is not None
        plan = PlanView(
            id=catalog.id,
            slug=catalog.slug,
            kind=catalog.kind,
            enabled=catalog.enabled,
            price=PriceView.model_validate(price),
        )
        entitlement = db.scalar(
            select(Entitlement)
            .where(
                Entitlement.user_id == user_id,
                Entitlement.price_version_id == price.id,
                Entitlement.starts_at <= now,
                or_(Entitlement.ends_at.is_(None), Entitlement.ends_at > now),
                ~Entitlement.id.in_(select(EntitlementRevocation.entitlement_id)),
            )
            .order_by(Entitlement.starts_at.desc(), Entitlement.id.desc())
            .limit(1)
        )
    return BillingOverview(
        plan=plan,
        access_source="entitlement"
        if entitlement
        else ("free_default" if plan else "unconfigured"),
        access_ends_at=entitlement.ends_at if entitlement else None,
        day_starts_at=day,
        month_starts_at=month,
        daily_used_credits=used(day),
        monthly_used_credits=used(month),
        held_reservations=states.get("HELD", (0, 0))[0],
        held_credits=states.get("HELD", (0, 0))[1],
        settled_credits=states.get("SETTLED", (0, 0))[1],
        released_credits=states.get("RELEASED", (0, 0))[1],
    )


@router.get("/me/billing", response_model=BillingOverview)
def my_billing(db: DB, user: CurrentUser) -> BillingOverview:
    return overview(db, user.id)


@router.get("/me/credit-reservations", response_model=ReservationPage)
def reservations(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> ReservationPage:
    query = select(CreditReservation).where(CreditReservation.user_id == user.id)
    if cursor:
        query = query.where(CreditReservation.id > cursor)
    rows = list(db.scalars(query.order_by(CreditReservation.id).limit(limit + 1)))
    return ReservationPage(
        items=[ReservationView.model_validate(r) for r in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/admin/customers", response_model=CustomerPage, tags=["admin"])
def customers(
    request: Request,
    db: DB,
    user: AdminUser,
    limit: int = Query(20, ge=1, le=100),
    cursor: UUID | None = None,
    search: str = Query("", max_length=100),
) -> CustomerPage:
    query = (
        select(User, Wallet.available, Wallet.reserved)
        .outerjoin(Wallet, Wallet.user_id == User.id)
        .where(User.role == "customer")
    )
    if search.strip():
        query = query.where(User.email.icontains(search.strip(), autoescape=True))
    if cursor:
        query = query.where(User.id > cursor)
    rows = db.execute(query.order_by(User.id).limit(limit + 1)).all()
    result = CustomerPage(
        items=[
            CustomerView(
                id=u.id,
                email=u.email,
                status=u.status,
                verified=u.verified,
                created_at=u.created_at,
                available_credits=available or 0,
                reserved_credits=reserved or 0,
            )
            for u, available, reserved in rows[:limit]
        ],
        next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
    )
    service.audit(db, user.id, "billing.customers_read", user.id)
    db.commit()
    return result


@router.get("/admin/customers/{user_id}/billing", response_model=BillingOverview, tags=["admin"])
def customer_billing(user_id: UUID, db: DB, user: AdminUser) -> BillingOverview:
    target = db.get(User, user_id)
    if not target or target.role != "customer":
        raise ApiError(404, "not_found", "Customer not found.")
    result = overview(db, target.id)
    service.audit(db, user.id, "billing.customer_read", target.id)
    db.commit()
    return result


@router.get("/admin/jobs", response_model=StaffJobPage, tags=["admin"])
def staff_jobs(
    db: DB, user: AdminUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> StaffJobPage:
    query = select(Job)
    if cursor:
        query = query.where(Job.id > cursor)
    rows = list(db.scalars(query.order_by(Job.id).limit(limit + 1)))
    result = StaffJobPage(
        items=[StaffJob(user_id=j.user_id, job=JobView.model_validate(j)) for j in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    service.audit(db, user.id, "jobs.staff_read", user.id)
    db.commit()
    return result


@router.get("/admin/dashboard", response_model=AdminOverview, tags=["admin"])
def admin_dashboard(db: DB, user: AdminUser) -> AdminOverview:
    from zoclip.credits.models import PlanPrice, SystemLimits

    now = utcnow()
    system = db.get(SystemLimits, 1)
    result = AdminOverview(
        customers=db.scalar(select(func.count()).select_from(User).where(User.role == "customer"))
        or 0,
        verified_customers=db.scalar(
            select(func.count()).select_from(User).where(User.role == "customer", User.verified)
        )
        or 0,
        available_credits=int(db.scalar(select(func.sum(Wallet.available))) or 0),
        reserved_credits=int(db.scalar(select(func.sum(Wallet.reserved))) or 0),
        active_prepaid_access=db.scalar(
            select(func.count())
            .select_from(Entitlement)
            .join(PlanPrice)
            .join(Plan)
            .where(
                Plan.kind == "plan",
                PlanPrice.valid_days == 30,
                Entitlement.starts_at <= now,
                Entitlement.ends_at > now,
                ~Entitlement.id.in_(select(EntitlementRevocation.entitlement_id)),
            )
        )
        or 0,
        job_states=dict(db.execute(select(Job.state, func.count()).group_by(Job.state)).all()),
        spending_blocked=not system or system.breaker or system.policy_id is None,
    )
    service.audit(db, user.id, "billing.dashboard_read", user.id)
    db.commit()
    return result
