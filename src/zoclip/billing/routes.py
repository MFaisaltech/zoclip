from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import EmailStr
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from zoclip.auth.dependencies import DB, AdminUser, CsrfSession, CurrentUser
from zoclip.auth.models import User
from zoclip.billing import manual, service
from zoclip.billing.models import BillingOrder, BillingRefund
from zoclip.billing.schemas import (
    CheckoutView,
    ManualPaymentInput,
    ManualRefundInput,
    ManualUserView,
    OrderInput,
    OrderPage,
    OrderView,
    RefundInput,
    RefundRequestView,
    RefundView,
    SandboxNotification,
    StaffAction,
    StaffOrderView,
)
from zoclip.core.errors import ApiError
from zoclip.core.rate_limit import rate_limit
from zoclip.credits.models import Entitlement, Plan, PlanPrice, Wallet
from zoclip.credits.schemas import Key
from zoclip.credits.service import audit, staff

router = APIRouter(prefix="/api/v1", tags=["billing"])
OperationKey = Annotated[Key, Header(alias="Idempotency-Key")]


@router.get("/admin/manual-payments/users", response_model=list[ManualUserView], tags=["admin"])
def manual_users(
    email: EmailStr, request: Request, db: DB, user: AdminUser
) -> list[ManualUserView]:
    rate_limit(request, "manual-payment-search", str(user.id))
    rows = db.execute(
        select(User, Wallet.available, Wallet.reserved)
        .outerjoin(Wallet, Wallet.user_id == User.id)
        .where(User.email == str(email).lower())
    ).all()
    audit(db, user.id, "billing.manual_user_search", rows[0][0].id if rows else user.id)
    result = [
        ManualUserView(
            id=u.id,
            email=u.email,
            verified=u.verified,
            status=u.status,
            available_credits=available or 0,
            reserved_credits=reserved or 0,
        )
        for u, available, reserved in rows
    ]
    db.commit()
    return result


@router.post(
    "/admin/manual-payments/users/{user_id}/activate", response_model=StaffOrderView, tags=["admin"]
)
def manual_activate(
    user_id: UUID,
    data: ManualPaymentInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> StaffOrderView:
    rate_limit(request, "manual-payment-write", str(user.id))
    row = manual.activate(db, request.app.state.settings, user.id, user_id, data, key)
    result = staff_view(db, row)
    db.commit()
    return result


@router.post(
    "/admin/manual-payments/{order_id}/refund", response_model=StaffOrderView, tags=["admin"]
)
def manual_refund(
    order_id: UUID,
    data: ManualRefundInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> StaffOrderView:
    rate_limit(request, "manual-payment-write", str(user.id))
    row = manual.refund(db, request.app.state.settings, user.id, order_id, data, key)
    result = staff_view(db, row)
    db.commit()
    return result


@router.post("/billing/orders", response_model=CheckoutView, status_code=201)
def create_order(
    data: OrderInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: CurrentUser,
    csrf: CsrfSession,
) -> CheckoutView:
    rate_limit(request, "billing-order", str(user.id))
    row = service.create_order(db, user.id, data, key, request.app.state.payment_provider)
    result = CheckoutView(order=service.view(row), reference=service.reference(db, row))
    db.commit()
    return result


@router.get("/billing/orders/{order_id}", response_model=OrderView)
def order(order_id: UUID, db: DB, user: CurrentUser) -> OrderView:
    # Browser return query parameters are deliberately never payment evidence.
    return service.view(service.owned_order(db, order_id, user.id))


@router.get("/billing/history", response_model=OrderPage)
def history(
    db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> OrderPage:
    query = (
        select(BillingOrder)
        .where(BillingOrder.user_id == user.id)
        .order_by(BillingOrder.id)
        .limit(limit + 1)
    )
    if cursor:
        service.owned_order(db, cursor, user.id)
        query = query.where(BillingOrder.id > cursor)
    rows = list(db.scalars(query))
    return OrderPage(
        items=[service.view(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.post(
    "/billing/webhooks/{provider}",
    response_model=OrderView,
    # Preserve exact raw bytes for authentication while exposing the same model
    # used by the adapter's JSON validation to SDK/frontend consumers.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": SandboxNotification.model_json_schema()}},
        }
    },
)
async def webhook(
    provider: str,
    request: Request,
    x_sandbox_timestamp: Annotated[str | None, Header()] = None,
    x_sandbox_signature: Annotated[str | None, Header()] = None,
) -> OrderView:
    adapter = request.app.state.payment_provider
    if provider != adapter.name:
        raise ApiError(503, "payments_disabled", "Requested payment adapter is disabled.")
    body = await request.body()

    def process() -> OrderView:
        rate_limit(request, "billing-webhook")
        evidence = adapter.verify_notification(
            body,
            {
                "x-sandbox-timestamp": x_sandbox_timestamp or "",
                "x-sandbox-signature": x_sandbox_signature or "",
            },
        )
        # The whole synchronous session belongs to this task/thread.
        with request.app.state.session_factory() as db:
            db.info["request_id"] = request.state.request_id
            result = service.view(service.apply_event(db, evidence))
            db.commit()
            return result

    return await run_in_threadpool(process)


def staff_view(db: DB, row: BillingOrder) -> StaffOrderView:
    refund = db.scalar(select(BillingRefund).where(BillingRefund.order_id == row.id))
    account = db.get(User, row.user_id)
    price = db.get(PlanPrice, row.price_version_id)
    plan = db.get(Plan, price.plan_id) if price else None
    entitlement = db.get(Entitlement, row.entitlement_id) if row.entitlement_id else None
    return StaffOrderView(
        order=service.view(row),
        user_id=row.user_id,
        reference=service.reference(db, row),
        refund=RefundView.model_validate(refund) if refund else None,
        customer_email=account.email if account else "",
        customer_name=row.customer_name,
        plan_slug=plan.slug if plan else "",
        access_starts_at=entitlement.starts_at if entitlement else None,
        access_ends_at=entitlement.ends_at if entitlement else None,
    )


@router.get("/admin/payments", response_model=list[StaffOrderView], tags=["admin"])
def staff_payments(
    db: DB, user: AdminUser, limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None
) -> list[StaffOrderView]:
    query = select(BillingOrder).order_by(BillingOrder.id).limit(limit)
    if cursor:
        query = query.where(BillingOrder.id > cursor)
    result = [staff_view(db, row) for row in db.scalars(query)]
    audit(db, user.id, "billing.staff_read", user.id)
    db.commit()
    return result


@router.post("/admin/payments/{order_id}/reconcile", response_model=StaffOrderView, tags=["admin"])
def reconcile(
    order_id: UUID,
    data: StaffAction,
    key: OperationKey,
    request: Request,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> StaffOrderView:
    staff(db, user.id, data.reason)
    row, _ = service.lock_order(db, order_id)
    ref, actor = service.reference(db, row), user.id
    db.commit()
    # No transaction spans provider IO. No evidence => no manual credit grant.
    evidence = request.app.state.payment_provider.query_transaction(ref)
    row = service.reconcile_order(
        db, order_id, actor, data.reason, key, evidence, accept_late=data.accept_late
    )
    result = staff_view(db, row)
    db.commit()
    return result


@router.post("/admin/payments/{order_id}/refund", response_model=RefundRequestView, tags=["admin"])
def refund(
    order_id: UUID,
    data: RefundInput,
    key: OperationKey,
    request: Request,
    db: DB,
    user: AdminUser,
    csrf: CsrfSession,
) -> RefundRequestView:
    row, fresh = service.begin_refund(db, order_id, user.id, data.reason, key)
    order = db.get(BillingOrder, order_id)
    assert order is not None
    ref = service.reference(db, order)
    db.commit()  # Durable UNKNOWN intent before any provider side effect.
    if fresh:
        evidence = request.app.state.payment_provider.refund_if_supported(ref, str(row.id))
        if evidence:
            if (
                evidence.notification.order_id != order_id
                or evidence.notification.status != "REFUNDED"
            ):
                raise ApiError(
                    409, "payment_mismatch", "Refund evidence does not match the request."
                )
            service.apply_event(db, evidence)
            db.commit()
    db.refresh(row)
    return RefundRequestView.model_validate(row)
