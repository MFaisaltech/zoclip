from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Credit = Annotated[int, Field(strict=True, ge=0, le=10**12)]
PositiveCredit = Annotated[int, Field(strict=True, ge=1, le=10**12)]


def exact_decimal(value: object) -> object:
    if isinstance(value, (float, bool)):
        raise ValueError("Use a decimal string for USD amounts")
    return value


USD = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    Field(ge=0, le=Decimal("1000000"), max_digits=20, decimal_places=10),
]
Key = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Reason = Annotated[str, Field(min_length=5, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ConsumptionRules(StrictModel):
    purchasable: bool = True
    lifetime_output_limit: PositiveCredit | None = None
    minimum_job_credits: Credit = 0
    credits_per_minute: Credit
    credits_per_output: Credit
    credits_per_edit: Credit
    captions_credits: Credit
    reframe_credits: Credit
    max_source_seconds: Annotated[int, Field(strict=True, ge=1, le=7200)]
    max_outputs: Annotated[int, Field(strict=True, ge=1, le=100)]
    max_edits: Annotated[int, Field(strict=True, ge=0, le=100)]
    max_concurrent_jobs: Annotated[int, Field(strict=True, ge=1, le=10)]
    daily_credits: PositiveCredit
    monthly_credits: PositiveCredit


class PlanVersionInput(StrictModel):
    price_paisa: Credit
    included_credits: Credit
    valid_days: Literal[0, 30]
    approved: bool = False
    rules: ConsumptionRules
    reason: Reason


class PriceView(StrictModel):
    id: UUID
    price_paisa: int
    included_credits: int
    valid_days: int
    approved: bool
    rules: ConsumptionRules


class PlanView(StrictModel):
    id: UUID
    slug: str
    kind: str
    enabled: bool
    currency: Literal["PKR"] = "PKR"
    auto_renews: Literal[False] = False
    credit_expiry: Literal["disabled"] = "disabled"
    price: PriceView | None


class WalletView(StrictModel):
    available_credits: int
    reserved_credits: int
    credit_expiry: Literal["disabled"] = "disabled"


class TransactionView(StrictModel):
    id: UUID
    operation: str
    available_delta: int
    reserved_delta: int
    available_after: int
    reserved_after: int
    reservation_id: UUID | None
    created_at: datetime


class TransactionPage(StrictModel):
    items: list[TransactionView]
    next_cursor: UUID | None


class EntitlementView(StrictModel):
    id: UUID
    price_version_id: UUID
    starts_at: datetime
    ends_at: datetime | None
    active: bool


class QuoteInput(StrictModel):
    source_seconds: Annotated[int, Field(strict=True, ge=1, le=7200)]
    output_count: Annotated[int, Field(strict=True, ge=1, le=100)]
    edit_count: Annotated[int, Field(strict=True, ge=0, le=100)] = 0
    captions: bool = True
    reframe: bool = True


class GenerationQuoteInput(QuoteInput):
    """Customer-facing generation quotes: the product sells 1-6 clips per job.

    Internal pricing math (calculate) keeps the wider QuoteInput bound; only
    the quote endpoints customers actually confirm are capped at 6 outputs.
    """

    output_count: Annotated[int, Field(strict=True, ge=1, le=6)]


class QuoteView(StrictModel):
    id: UUID
    price_version_id: UUID
    credits: int
    request: QuoteInput
    expires_at: datetime


class QuotePreviewView(StrictModel):
    """Non-redeemable preview: no quote ID, allowance, or reservation."""

    preview_only: Literal[True] = True
    processing_enabled: Literal[False] = False
    pricing_status: Literal["unconfigured", "unapproved", "configured"]
    price_version_id: UUID | None
    credits: int | None
    request: QuoteInput


class AdjustmentInput(StrictModel):
    amount: Annotated[int, Field(strict=True, ge=-(10**12), le=10**12)]
    reason: Reason

    @model_validator(mode="after")
    def nonzero(self) -> "AdjustmentInput":
        if self.amount == 0:
            raise ValueError("Nonzero adjustment required")
        return self


class EntitlementInput(StrictModel):
    price_version_id: UUID
    reason: Reason


class RateInput(StrictModel):
    component: Literal["deepgram", "gemini_input", "gemini_output", "render", "storage"]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    unit: Literal["minute", "token", "cpu_second", "gb_day"]
    unit_usd: Annotated[USD, Field(gt=0)]
    max_units: Annotated[int, Field(strict=True, ge=1, le=10**12)]
    reason: Reason


class RateView(RateInput):
    id: UUID


class BudgetLimits(StrictModel):
    per_job_usd: USD
    user_daily_usd: USD
    user_monthly_usd: USD
    global_daily_usd: USD
    global_monthly_usd: USD
    max_open_reservations: Annotated[int, Field(strict=True, ge=1, le=1000)]
    rate_ids: list[UUID] = Field(min_length=1, max_length=5)
    input_tokens_per_second: Annotated[int, Field(strict=True, ge=1, le=1000)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=100000)]
    render_cpu_seconds_per_output: Annotated[int, Field(strict=True, ge=1, le=100000)]
    storage_gb_days_per_output: Annotated[int, Field(strict=True, ge=1, le=10000)]
    max_attempts_per_job: Annotated[int, Field(strict=True, ge=1, le=100)]


class PolicyInput(StrictModel):
    limits: BudgetLimits
    breaker: bool = False
    reason: Reason


class PolicyView(StrictModel):
    id: UUID
    limits: BudgetLimits
    breaker: bool


class UsageView(StrictModel):
    estimated_usd: Decimal
    actual_usd: Decimal
    held_or_unknown_usd: Decimal
    attempts: int
