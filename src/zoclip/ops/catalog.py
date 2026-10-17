"""Audited private-staging catalog installation; grants no credit or access."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.credits import service
from zoclip.credits.models import Plan, PlanPrice, SystemLimits
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput, QuoteInput


def install(db: Session, settings: Settings, actor: UUID, catalog: dict) -> list[dict]:
    system = db.scalar(select(SystemLimits).where(SystemLimits.id == 1).with_for_update())
    if (
        not settings.private_staging
        or settings.ai_enabled
        or settings.payment_provider != "disabled"
        or settings.enable_live_payments
        or settings.enable_trial_credits
        or system is None
        or not system.breaker
    ):
        raise RuntimeError("Catalog installation requires closed private staging controls")
    service.staff(db, actor, catalog["reason"])
    result = []
    for slug, terms in catalog["plans"].items():
        plan = db.scalar(select(Plan).where(Plan.slug == slug))
        if plan is None and slug == "starter":
            plan = Plan(slug=slug, kind="plan")
            db.add(plan)
            db.flush()
        if plan is None or not plan.enabled:
            raise RuntimeError("Catalog references an absent or disabled plan")
        data = PlanVersionInput.model_validate({**terms, "reason": catalog["reason"]})
        if slug == "free" and (
            data.rules.max_source_seconds != 300
            or data.rules.max_outputs != 1
            or data.rules.max_edits != 0
            or data.rules.lifetime_output_limit != 1
            or data.rules.purchasable
            or data.included_credits
            != service.calculate(QuoteInput(source_seconds=300, output_count=1), data.rules)
        ):
            raise RuntimeError("Trial terms must cover exactly one bounded lifetime clip")
        if slug != "free" and data.approved:
            raise RuntimeError("Retail packages remain unapproved until measured acceptance")
        row = service.configure_plan(db, plan.id, data, catalog["version"], actor)
        result.append({"slug": slug, "price_version_id": str(row.id), "approved": row.approved})
    # Append retirement terms; existing orders and entitlements retain their snapshots.
    for slug in catalog.get("retired", []):
        plan = db.scalar(select(Plan).where(Plan.slug == slug))
        if not plan:
            continue
        old = db.scalar(
            select(PlanPrice)
            .where(PlanPrice.plan_id == plan.id)
            .order_by(PlanPrice.created_at.desc(), PlanPrice.id.desc())
            .limit(1)
        )
        rules = ConsumptionRules.model_validate(
            old.rules if old else catalog["plans"]["pro"]["rules"]
        )
        data = PlanVersionInput(
            price_paisa=old.price_paisa if old else 0,
            included_credits=old.included_credits if old else 0,
            valid_days=0 if plan.kind == "topup" else 30,
            approved=False,
            rules=rules.model_copy(update={"purchasable": False}),
            reason=catalog["reason"],
        )
        service.configure_plan(db, plan.id, data, catalog["version"], actor)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--actor", type=UUID, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    with Session(build_engine(settings.database_url.get_secret_value())) as db:
        result = install(db, settings, args.actor, catalog)
        if args.execute:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"committed": args.execute, "plans": result, "credits_granted": 0}))


if __name__ == "__main__":
    main()
