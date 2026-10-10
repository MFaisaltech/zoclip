"""Bounded SQL aggregates, explicit versioned reporting assumptions, no money mutation."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.billing.models import BillingOrder, BillingRefund, PaymentEvent
from zoclip.credits.models import CostRate, CreditReservation, ProviderUsage, SpendAttempt
from zoclip.credits.schemas import StrictModel
from zoclip.media.models import Job, Outbox, StorageObject
from zoclip.ops.schemas import OperationReport


class ReportingPolicy(StrictModel):
    version: str = Field(min_length=1, max_length=100)
    vps_monthly_usd: Decimal = Field(strict=True, ge=0, le=10000, max_digits=20, decimal_places=10)
    usd_pkr: Decimal = Field(strict=True, gt=0, le=100000, max_digits=20, decimal_places=10)
    margin_target: Decimal = Field(strict=True, ge=0, le=1, max_digits=11, decimal_places=10)
    rate_source: str = Field(min_length=5, max_length=200)


def reporting_policy(path: Path) -> tuple[ReportingPolicy, str] | None:
    raw = path.read_bytes()
    if len(raw) > 4096:
        raise ValueError("Reporting policy too large")
    # JSON strings only: never construct Decimal from a floating-point number.
    values = json.loads(raw)
    if values == {"enabled": False}:
        return None
    for key in ("vps_monthly_usd", "usd_pkr", "margin_target"):
        if not isinstance(values.get(key), str):
            raise ValueError("Reporting amounts must be decimal strings")
        values[key] = Decimal(values[key])
    return ReportingPolicy.model_validate(values), hashlib.sha256(raw).hexdigest()


def report(
    db: Session,
    start: datetime,
    end: datetime,
    media_root: str,
    policy_path: Path = Path("/run/secrets/reporting_policy"),
) -> dict:
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or start.utcoffset() != UTC.utcoffset(start)
        or end.utcoffset() != UTC.utcoffset(end)
        or not start < end
        or start.day != 1
        or start.hour
        or start.minute
        or start.second
        or start.microsecond
    ):
        raise ValueError("Use UTC month start and a later end in that month")
    next_month = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=UTC)
    if end > next_month:
        raise ValueError("Report period must fit one UTC calendar month")
    scope = (ProviderUsage.created_at >= start, ProviderUsage.created_at < end)
    usage = db.execute(
        select(
            CostRate.component,
            CostRate.unit,
            func.sum(ProviderUsage.units),
            func.sum(ProviderUsage.actual_usd),
        )
        .join(SpendAttempt, SpendAttempt.id == ProviderUsage.attempt_id)
        .join(CostRate, CostRate.id == SpendAttempt.rate_id)
        .where(*scope)
        .group_by(CostRate.component, CostRate.unit)
    ).all()
    actual = sum((row[3] for row in usage), Decimal(0))
    failed = db.scalar(
        select(func.coalesce(func.sum(ProviderUsage.actual_usd), 0))
        .join(SpendAttempt, SpendAttempt.id == ProviderUsage.attempt_id)
        .join(CreditReservation, CreditReservation.id == SpendAttempt.reservation_id)
        .join(Job, Job.id == CreditReservation.job_id)
        .where(*scope, Job.state.in_(["FAILED", "CANCELED"]))
    )
    exposure = db.scalar(
        select(func.coalesce(func.sum(SpendAttempt.estimated_usd), 0)).where(
            SpendAttempt.state.in_(["HELD", "UNKNOWN"])
        )
    )
    gross = db.scalar(
        select(func.coalesce(func.sum(BillingOrder.amount_paisa), 0)).where(
            BillingOrder.paid_at >= start, BillingOrder.paid_at < end
        )
    )
    reversed_paisa = db.scalar(
        select(func.coalesce(func.sum(BillingRefund.amount_paisa), 0)).where(
            BillingRefund.created_at >= start, BillingRefund.created_at < end
        )
    )
    # Count one successful capture's fee per order; duplicate success events are not fees.
    fee_rows = (
        select(PaymentEvent.order_id, func.max(PaymentEvent.fee_paisa).label("fee"))
        .join(BillingOrder, BillingOrder.id == PaymentEvent.order_id)
        .where(
            BillingOrder.paid_at >= start,
            BillingOrder.paid_at < end,
            PaymentEvent.status == "SUCCEEDED",
        )
        .group_by(PaymentEvent.order_id)
        .subquery()
    )
    fees = db.scalar(select(func.coalesce(func.sum(fee_rows.c.fee), 0))) or 0
    gross, reversed_paisa = gross or 0, reversed_paisa or 0
    states = dict(db.execute(select(Job.state, func.count()).group_by(Job.state)).all())
    storage = db.execute(
        select(
            func.coalesce(func.sum(StorageObject.materialized_bytes), 0),
            func.coalesce(func.sum(StorageObject.reserved_bytes), 0),
        ).where(StorageObject.deleted.is_(False))
    ).one()
    oldest = db.scalar(select(func.min(Outbox.created_at)).where(Outbox.dispatched_at.is_(None)))
    result: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "usage": [
            {"component": r[0], "unit": r[1], "units": r[2], "actual_usd": str(r[3])} for r in usage
        ],
        "actual_usd": str(actual),
        "failed_reservation_cost_usd": str(failed),
        "held_or_unknown_usd_all_periods": str(exposure),
        "gross_paisa": gross,
        "reversed_paisa": reversed_paisa,
        "fee_paisa": fees,
        "job_states": states,
        "media_materialized_bytes": storage[0],
        "media_reserved_bytes": storage[1],
        "disk_free_bytes": shutil.disk_usage(
            Path(media_root) if Path(media_root).exists() else Path(media_root).parent
        ).free,
        "oldest_pending_outbox_at": oldest.isoformat() if oldest else None,
        "economics": None,
        "limitations": (
            "Reservation-level failed cost; prepaid edits may share the original reservation. "
            "Compute/storage allocations are not invoices. Tax and unrecorded fees excluded. "
            "Mock PKR is fictional; margin is a scenario estimate, not verified profit."
        ),
    }
    policy_result = reporting_policy(policy_path) if policy_path.exists() else None
    if policy_result:
        policy, digest = policy_result
        allocation = (
            policy.vps_monthly_usd
            * Decimal(int((end - start).total_seconds()))
            / Decimal(int((next_month - start).total_seconds()))
        )
        net_pkr = Decimal(gross - reversed_paisa - fees) / 100
        cost_pkr = (actual + allocation) * policy.usd_pkr
        margin = (net_pkr - cost_pkr) / net_pkr if net_pkr > 0 else None
        result["economics"] = {
            "assumptions_version": policy.version,
            "assumptions_sha256": digest,
            "rate_source": policy.rate_source,
            "usd_pkr": str(policy.usd_pkr),
            "vps_allocated_usd": str(allocation),
            "net_pkr": str(net_pkr),
            "modeled_cost_pkr": str(cost_pkr),
            "margin": str(margin) if margin is not None else None,
            "below_target": margin < policy.margin_target if margin is not None else None,
        }
    # PostgreSQL SUM(bigint) returns NUMERIC/Decimal; emit exact JSON integers
    # through the same contract used by the API and the local monitor.
    return OperationReport.model_validate(result).model_dump(mode="json")
