from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from zoclip.credits.schemas import Key, PositiveCredit, Reason, StrictModel


class OrderInput(StrictModel):
    price_version_id: UUID


class OrderView(StrictModel):
    id: UUID
    price_version_id: UUID
    provider: str
    amount_paisa: int
    currency: Literal["PKR"]
    credits: int
    valid_days: int
    state: str
    expires_at: datetime
    paid_at: datetime | None
    created_at: datetime
    sandbox: Literal[True] = True
    auto_renews: Literal[False] = False


class CheckoutView(StrictModel):
    order: OrderView
    reference: str
    checkout_url: None = None
    instructions: Literal["Development sandbox only; no money is collected."] = (
        "Development sandbox only; no money is collected."
    )


class OrderPage(StrictModel):
    items: list[OrderView]
    next_cursor: UUID | None


class SandboxNotification(StrictModel):
    event_id: Key
    order_id: UUID
    reference: Key
    status: Literal["PENDING", "FAILED", "SUCCEEDED", "REFUNDED", "CHARGEBACK"]
    amount_paisa: PositiveCredit
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    fee_paisa: Annotated[int, Field(strict=True, ge=0, le=10**12)] = 0
    occurred_at: datetime


class StaffAction(StrictModel):
    reason: Reason
    accept_late: bool = False


class RefundInput(StrictModel):
    reason: Reason


class RefundView(StrictModel):
    id: UUID
    order_id: UUID
    kind: str
    amount_paisa: int
    recovered_credits: int
    unrecovered_credits: int


class StaffOrderView(StrictModel):
    order: OrderView
    user_id: UUID
    reference: str
    refund: RefundView | None


class RefundRequestView(StrictModel):
    id: UUID
    order_id: UUID
    state: str
