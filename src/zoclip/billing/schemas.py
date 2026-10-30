from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

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
    sandbox: bool = True
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


class ManualPaymentInput(StrictModel):
    price_version_id: UUID
    amount_paisa: PositiveCredit
    # The name the payer used (WhatsApp/bank sender name), entered in
    # Admin -> Purchases. Accounts carry no name field, so this record is
    # what Payments and Customers display; it is bound into the payload
    # fingerprint, so a replay under a different name conflicts.
    customer_name: Annotated[str, Field(min_length=2, max_length=120)]
    payment_reference: Annotated[
        str, Field(min_length=6, max_length=100, pattern=r"^[A-Za-z0-9 .:_-]+$")
    ]
    independently_verified: Literal[True]
    reason: Reason

    @field_validator("customer_name")
    @classmethod
    def canonical_name(cls, value: str) -> str:
        name = " ".join(value.split())
        if len(name) < 2:
            raise ValueError("Enter the customer's name")
        return name

    @field_validator("payment_reference")
    @classmethod
    def canonical_reference(cls, value: str) -> str:
        import re

        reference = re.sub(r"[^A-Z0-9]", "", value.upper())
        if len(reference) < 6:
            raise ValueError("Use the full bank or wallet transaction reference")
        return reference


class ManualRefundInput(StrictModel):
    payment_reference: Annotated[
        str, Field(min_length=6, max_length=100, pattern=r"^[A-Za-z0-9]+$")
    ]
    independently_verified: Literal[True]
    reason: Reason


class ManualUserView(StrictModel):
    id: UUID
    email: str
    verified: bool
    status: str
    available_credits: int
    reserved_credits: int


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
    # Readable payment-table fields (Admin -> Payments). Technical IDs stay
    # on the order itself for the secondary details view.
    customer_email: str
    customer_name: str | None
    plan_slug: str
    access_starts_at: datetime | None
    access_ends_at: datetime | None


class RefundRequestView(StrictModel):
    id: UUID
    order_id: UUID
    state: str
