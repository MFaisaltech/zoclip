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
from zoclip.credits.models import Plan, SystemLimits
from zoclip.credits.schemas import PlanVersionInput


def install(db: Session, settings: Settings, actor: UUID, catalog: dict) -> list[dict]:
    system = db.scalar(select(SystemLimits).where(SystemLimits.id == 1).with_for_update())
    if (
        not settings.private_staging
        or settings.ai_enabled
        or settings.payment_provider != "disabled"
        or settings.enable_live_payments
        or system is None
        or not system.breaker
    ):
        raise RuntimeError("Catalog installation requires closed private staging controls")
    service.staff(db, actor, catalog["reason"])
    result = []
    for slug, terms in catalog["plans"].items():
        plan = db.scalar(select(Plan).where(Plan.slug == slug))
        if plan is None or not plan.enabled:
            raise RuntimeError("Catalog references an absent or disabled plan")
        data = PlanVersionInput.model_validate({**terms, "reason": catalog["reason"]})
        if slug == "free" and data.included_credits:
            raise RuntimeError("Default processing terms must not grant free AI credits")
        if slug != "free" and data.approved:
            raise RuntimeError("Retail packages remain unapproved until measured acceptance")
        row = service.configure_plan(db, plan.id, data, catalog["version"], actor)
        result.append({"slug": slug, "price_version_id": str(row.id), "approved": row.approved})
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
