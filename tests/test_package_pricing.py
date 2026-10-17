"""Current commercial terms, real PG accounting; fictional signed payments only."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import test_billing
import test_credits
from sqlalchemy import func, select

from zoclip.billing import service as billing
from zoclip.billing.models import BillingOrder
from zoclip.billing.providers import MockSandboxProvider
from zoclip.billing.schemas import OrderInput
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.credits import service as credits
from zoclip.credits.models import (
    CreditReservation,
    CreditTransaction,
    Entitlement,
    Plan,
    PlanPrice,
    SystemLimits,
)
from zoclip.credits.routes import plans as listed_plans
from zoclip.credits.schemas import PlanVersionInput, QuoteInput
from zoclip.ops.catalog import install

financial_database = test_credits.concurrent_db
CATALOG = json.loads(Path("deploy/staging-catalog.json").read_text())


@pytest.fixture
def packages(financial_database):
    factory, users = financial_database
    config = Settings(
        _env_file=None,
        app_env="production",
        private_staging=True,
        database_url=factory.kw["bind"].url.render_as_string(hide_password=False),
        allowed_hosts=["api.example.com"],
        staging_site_domain="example.com",
        public_app_url="https://app.example.com",
        api_public_url="https://api.example.com",
    )
    with factory() as db:
        for name in ["alice", "bob"]:
            credits.adjust(
                db,
                users[name],
                -5,
                "remove-fixture-seed",
                users["admin"],
                "Remove fictional fixture seed",
            )
        db.get(SystemLimits, 1).breaker = True
        before = db.scalar(select(func.count()).select_from(CreditTransaction))
        rows = install(db, config, users["admin"], CATALOG)
        assert install(db, config, users["admin"], CATALOG) == rows
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == before
        assert db.scalar(select(func.count()).select_from(Entitlement)) == 0
        users["prices"].update({r["slug"]: r["price_version_id"] for r in rows})
        from uuid import UUID

        users["prices"] = {
            k: UUID(v) if isinstance(v, str) else v for k, v in users["prices"].items()
        }
        db.get(SystemLimits, 1).breaker = False  # Fictional local expense policy only.
        db.commit()
    return factory, users, MockSandboxProvider(test_billing.SECRET)


@pytest.mark.parametrize(
    "slug,paisa,total,bonus,target",
    [
        ("starter", 29900, 500, 0, 7),
        ("creator", 69900, 1300, 100, 20),
        ("pro", 129900, 2400, 150, 38),
    ],
)
def test_purchase_grants_total_once_and_deducts_exact_duration_quote(
    packages, slug, paisa, total, bonus, target
):
    factory, users, _ = packages
    order = test_billing.new_order(packages, slug=slug)
    with factory() as db:
        snapshot = db.get(BillingOrder, order)
        assert (snapshot.amount_paisa, snapshot.credits, snapshot.currency) == (paisa, total, "PKR")
        assert credits.lock_wallet(db, users["alice"]).available == 0
    data = test_billing.notification(packages, order)
    assert test_billing.apply(packages, data) == "PAID"
    assert test_billing.apply(packages, data) == "PAID"
    assert (
        test_billing.apply(packages, data.model_copy(update={"event_id": str(uuid4())})) == "PAID"
    )
    with factory() as db:
        assert (
            credits.lock_wallet(db, users["alice"]).available == total
        )  # Bonus is already included.
        assert CATALOG["display"][slug]["bonus_credits"] == bonus
        grants = db.scalars(
            select(CreditTransaction).where(
                CreditTransaction.user_id == users["alice"], CreditTransaction.operation == "GRANT"
            )
        ).all()
        assert len(grants) == 2  # Original 5-credit fixture grant + exactly one purchase.
        short = credits.make_quote(
            db, users["alice"], QuoteInput(source_seconds=60, output_count=1), "short"
        )
        long = credits.make_quote(
            db, users["alice"], QuoteInput(source_seconds=900, output_count=1), "long"
        )
        assert short.credits == 60 and long.credits == 77
        assert long.credits * target > total  # Targets never replace actual video quotes.
        held = credits.reserve(db, users["alice"], long.id, uuid4(), "reserve-long")
        assert (
            credits.lock_wallet(db, users["alice"]).available,
            credits.lock_wallet(db, users["alice"]).reserved,
        ) == (total - 77, 77)
        credits.finish(
            db,
            users["alice"],
            held.id,
            "settle-long",
            success=True,
            evidence="fictional-verified-local-output",
        )
        credits.finish(
            db,
            users["alice"],
            held.id,
            "settle-long",
            success=True,
            evidence="fictional-verified-local-output",
        )
        wallet = credits.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (total - 77, 0)
        credits.reconcile(db, wallet)
        db.commit()


def test_long_source_cannot_spend_starter_target_instead_of_actual_credits(packages):
    factory, users, _ = packages
    order = test_billing.new_order(packages, slug="starter")
    test_billing.apply(packages, test_billing.notification(packages, order))
    with factory() as db:
        quote = credits.make_quote(
            db, users["alice"], QuoteInput(source_seconds=7200, output_count=1), "two-hour"
        )
        assert quote.credits == 602
        with pytest.raises(ApiError, match="insufficient_credits"):
            credits.reserve(db, users["alice"], quote.id, uuid4(), "too-expensive")
        assert credits.lock_wallet(db, users["alice"]).available == 500
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_new_catalog_hides_retired_sales_without_deleting_history(packages):
    factory, users, provider = packages
    with factory() as db:
        assert {p.slug for p in listed_plans(db)} == {"free", "starter", "creator", "pro"}
        for slug in ["business", "topup"]:
            plan = db.scalar(select(Plan).where(Plan.slug == slug))
            versions = db.scalars(
                select(PlanPrice)
                .where(PlanPrice.plan_id == plan.id)
                .order_by(PlanPrice.created_at.desc())
            ).all()
            assert len(versions) >= 2 and plan.enabled
            with pytest.raises(ApiError, match="price_unavailable"):
                billing.create_order(
                    db, users["alice"], OrderInput(price_version_id=versions[0].id), slug, provider
                )


def trial(factory, users):
    with factory() as db:
        row = credits.grant_entitlement(
            db,
            users["alice"],
            users["prices"]["free"],
            "trial",
            users["admin"],
            "Fictional local trial allowance",
        )
        assert (
            credits.grant_entitlement(
                db,
                users["alice"],
                users["prices"]["free"],
                "trial",
                users["admin"],
                "Fictional local trial allowance",
            ).id
            == row.id
        )
        with pytest.raises(ApiError, match="allowance_already_granted"):
            credits.grant_entitlement(
                db,
                users["alice"],
                users["prices"]["free"],
                "trial-again",
                users["admin"],
                "Fictional local trial allowance",
            )
        # Extra unrelated credits cannot buy another free-plan output.
        credits.adjust(
            db,
            users["alice"],
            1000,
            "extra-fixture",
            users["admin"],
            "Fictional balance to test lifetime limit",
            grant=True,
        )
        first = credits.make_quote(
            db, users["alice"], QuoteInput(source_seconds=300, output_count=1), "trial-one"
        )
        second = credits.make_quote(
            db, users["alice"], QuoteInput.model_validate(first.request), "trial-two"
        )
        for request in [
            QuoteInput(source_seconds=301, output_count=1),
            QuoteInput(source_seconds=26, output_count=2),
        ]:
            with pytest.raises(ApiError, match="plan_limit"):
                credits.make_quote(db, users["alice"], request, str(uuid4()))
        db.commit()
        return first.id, second.id


def test_trial_lifetime_limit_survives_new_sessions_and_versions(packages):
    factory, users, _ = packages
    first, second = trial(factory, users)
    with factory() as db:
        held = credits.reserve(db, users["alice"], first, uuid4(), "first-trial")
        credits.finish(
            db, users["alice"], held.id, "trial-done", success=True, evidence="fictional-output"
        )
        db.commit()
    with factory() as db:
        with pytest.raises(ApiError, match="lifetime_output_limit"):
            credits.reserve(db, users["alice"], second, uuid4(), "second-trial")
        old = db.get(PlanPrice, users["prices"]["free"])
        credits.configure_plan(
            db,
            old.plan_id,
            PlanVersionInput.model_validate(
                {**CATALOG["plans"]["free"], "reason": CATALOG["reason"]}
            ),
            "future-trial-version",
            users["admin"],
        )
        db.commit()
    with factory() as db:
        with pytest.raises(ApiError, match="lifetime_output_limit"):
            credits.make_quote(
                db, users["alice"], QuoteInput(source_seconds=26, output_count=1), "reset-attempt"
            )


def test_concurrent_trial_dispatch_has_one_winner(packages):
    factory, users, _ = packages
    ids = trial(factory, users)
    barrier = Barrier(2)

    def contender(quote_id):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                credits.reserve(db, users["alice"], quote_id, uuid4(), str(uuid4()))
                db.commit()
                return "held"
            except ApiError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(contender, ids)) == ["held", "lifetime_output_limit"]


def test_trial_failure_releases_credits_and_spending_breaker_still_blocks(packages):
    factory, users, _ = packages
    first, second = trial(factory, users)
    with factory() as db:
        held = credits.reserve(db, users["alice"], first, uuid4(), "failed-trial")
        credits.finish(
            db,
            users["alice"],
            held.id,
            "release-trial",
            success=False,
            evidence="proven-local-failure",
        )
        db.get(SystemLimits, 1).breaker = True
        db.commit()
    with factory() as db:
        with pytest.raises(ApiError, match="spending_disabled"):
            credits.reserve(db, users["alice"], second, uuid4(), "closed-breaker")
        assert credits.lock_wallet(db, users["alice"]).available == 1060
