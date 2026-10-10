"""Private local alert evaluation. No outbound notifier or paid request."""

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from redis import Redis
from rq import Worker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.ai.models import AIRequest
from zoclip.billing.models import BillingRefund
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.credits.models import CostPolicy, ProviderUsage, SpendAttempt, SystemLimits
from zoclip.media.models import Job
from zoclip.ops.report import report


def snapshot(db: Session, settings: Settings) -> dict:
    now = utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = report(db, start, now, settings.media_root)
    alerts = []
    if result["disk_free_bytes"] < settings.media_headroom_bytes + 2 * 1024**3:
        alerts.append("disk_headroom_low")
    if Decimal(result["held_or_unknown_usd_all_periods"]) > 0:
        alerts.append("provider_exposure_needs_review")
    if result["economics"] and result["economics"]["below_target"]:
        alerts.append("margin_below_target")
    counts = dict(
        db.execute(
            select(Job.state, func.count())
            .where(Job.updated_at >= now - timedelta(hours=1))
            .group_by(Job.state)
        ).all()
    )
    failures = counts.get("FAILED", 0)
    total = sum(counts.values())
    if failures >= 3 and failures * 5 >= total:
        alerts.append("job_failure_rate_high")
    if (
        db.scalar(
            select(func.count())
            .select_from(AIRequest)
            .where(AIRequest.state == "REJECTED", AIRequest.updated_at >= now - timedelta(hours=1))
        )
        or 0
    ) >= 3:
        alerts.append("provider_429_spike")
    if (
        db.scalar(
            select(func.count())
            .select_from(BillingRefund)
            .where(BillingRefund.created_at >= now - timedelta(hours=1))
        )
        or 0
    ) >= 3:
        alerts.append("payment_reversal_spike")
    if db.scalar(
        select(BillingRefund.id)
        .where(
            BillingRefund.kind == "CHARGEBACK", BillingRefund.created_at >= now - timedelta(hours=1)
        )
        .limit(1)
    ):
        alerts.append("chargeback_review")
    if result["oldest_pending_outbox_at"]:
        from datetime import datetime

        if (now - datetime.fromisoformat(result["oldest_pending_outbox_at"])).total_seconds() > 120:
            alerts.append("outbox_stalled")
    system = db.get(SystemLimits, 1)
    policy = db.get(CostPolicy, system.policy_id) if system and system.policy_id else None
    for period, boundary in (
        ("daily", now.replace(hour=0, minute=0, second=0, microsecond=0)),
        ("monthly", start),
    ):
        cost = db.scalar(
            select(func.coalesce(func.sum(ProviderUsage.actual_usd), 0)).where(
                ProviderUsage.created_at >= boundary
            )
        ) or Decimal(0)
        hold = db.scalar(
            select(func.coalesce(func.sum(SpendAttempt.estimated_usd), 0)).where(
                SpendAttempt.state.in_(["HELD", "UNKNOWN"])
            )
        ) or Decimal(0)
        if policy and cost + hold >= Decimal(policy.limits[f"global_{period}_usd"]) * Decimal(
            "0.8"
        ):
            alerts.append(f"{period}_spend_at_80_percent")
    result["alerts"] = alerts
    result["spending_disabled"] = not policy or bool(system and system.breaker)
    return result


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            result = snapshot(db, settings)
        with Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=3) as redis:
            workers = Worker.all(connection=redis)
            for name in ("zoclip-ai", "zoclip-render"):
                matching = [w for w in workers if w.name.startswith(name + "-")]
                worker = max(
                    matching,
                    key=lambda w: w.last_heartbeat or utcnow() - timedelta(days=1),
                    default=None,
                )
                if (
                    not worker
                    or not worker.last_heartbeat
                    or (utcnow() - worker.last_heartbeat).total_seconds() >= 480
                ):
                    result["alerts"].append(name + "_dead")
        if utcnow().timestamp() - Path("/tmp/zoclip-maintenance-heartbeat").stat().st_mtime >= 120:
            result["alerts"].append("maintenance_stale")
        print(json.dumps(result))
        if result["alerts"]:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {"alerts": ["monitor_dependency_failure"], "error_class": type(exc).__name__}
            )
        )
        raise SystemExit(1) from None
