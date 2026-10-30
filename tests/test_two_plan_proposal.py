"""Inactive proposal only: no real balances, providers or deployment changes."""

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
import test_billing
import test_package_pricing
from pydantic import ValidationError
from sqlalchemy import func, select

from scripts.prepare_two_plan_proposal import proposal
from scripts.two_plan_economics import report
from zoclip.billing.models import BillingOrder
from zoclip.core.config import Settings
from zoclip.credits import service as credits
from zoclip.credits.models import CreditTransaction, PlanPrice, SystemLimits
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput, QuoteInput
from zoclip.ops.catalog import install

financial_database = test_package_pricing.financial_database
packages = test_package_pricing.packages


def test_proposal_preserves_trial_and_has_exact_two_prepaid_packages():
    current = json.loads(Path("tests/fixtures/legacy-catalog.json").read_text())
    draft = proposal()
    assert draft == json.loads(Path("deploy/pricing-proposal-20261020.json").read_text())
    assert draft["release_status"] == "proposal"
    assert set(draft["plans"]) == {"free", "creator", "pro"}
    assert "starter" in draft["retired"]
    assert draft["plans"]["free"] == current["plans"]["free"]
    for slug, paisa, amount, target in [("creator", 200000, 3700, 61), ("pro", 500000, 9500, 158)]:
        terms = draft["plans"][slug]
        assert (terms["price_paisa"], terms["included_credits"]) == (paisa, amount)
        assert not terms["approved"] and terms["valid_days"] == 30
        with pytest.raises(ValidationError):
            PlanVersionInput.model_validate({**terms, "reason": draft["reason"]})
        rules = ConsumptionRules.model_validate(terms["rules"])
        quote = credits.calculate(QuoteInput(source_seconds=300, output_count=1), rules)
        assert draft["display"][slug]["target_clips"] == amount // quote == target
        assert rules.monthly_credits >= amount
        assert draft["display"][slug]["bonus_credits"] == 0
        assert credits.calculate(QuoteInput(source_seconds=7200, output_count=1), rules) == 602
    creator, pro = (draft["plans"][name] for name in ["creator", "pro"])
    assert Decimal(pro["price_paisa"]) / pro["included_credits"] < (
        Decimal(creator["price_paisa"]) / creator["included_credits"]
    )


def test_economic_gate_fails_and_conditional_ceiling_solves_margin_inequality():
    result = report()
    assert not result["activation_allowed"]
    config = result["assumptions"]
    for profile in result["profiles"].values():
        for terms in profile.values():
            assert not terms["proposed_passes_assumed_target"]
            assert Decimal(terms["proposed_worst_margin_fraction"]) < 0
            ceiling = terms["conditional_max_credits_for_target"]
            price = Decimal(terms["price_pkr"]) / Decimal(str(config["assumed_pkr_per_usd"]))
            allowed = price * (
                1
                - Decimal(config["assumed_payment_fee_fraction"])
                - Decimal(config["target_contribution_fraction"])
            ) - Decimal(config["assumed_fixed_fee_usd"])
            cost = Decimal(terms["worst_quoted_scenario"]["cost_per_credit_usd"])
            assert ceiling * cost <= allowed < (ceiling + 1) * cost
            assert all(s["deepgram_api_usd"] == "0" for s in terms["scenarios"])


def test_missing_evidence_is_not_turned_into_approval_by_optimistic_assumptions():
    config = deepcopy(report()["assumptions"])
    config["assumed_monthly_completed_jobs"] = 1000000
    config["target_contribution_fraction"] = "0"
    assert not report(config)["activation_allowed"]


def test_operator_rejects_proposal_before_any_database_or_credit_mutation(packages):
    factory, users, _ = packages
    with factory() as db:
        versions = db.scalar(select(func.count()).select_from(PlanPrice))
        ledger = db.scalar(select(func.count()).select_from(CreditTransaction))
        wallet = credits.lock_wallet(db, users["alice"])
        before = (wallet.available, wallet.reserved)
        db.get(SystemLimits, 1).breaker = True
        # The proposal is rejected even before settings or database admission.
        with pytest.raises(RuntimeError, match="economics and owner review"):
            install(db, None, users["admin"], proposal())
        assert db.scalar(select(func.count()).select_from(PlanPrice)) == versions
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == ledger
        assert (wallet.available, wallet.reserved) == before


@pytest.mark.parametrize("slug,amount,paisa", [("creator", 3700, 200000), ("pro", 9500, 500000)])
def test_future_reviewed_catalog_preserves_old_orders_and_grants_new_total_once(
    packages, slug, amount, paisa
):
    # Deliberately simulates future reviewed terms in a disposable DB only.
    # The real proposal file/operator remains blocked and no live pricing is installed.
    from uuid import UUID, uuid4

    from zoclip.credits.routes import plans

    factory, users, _ = packages
    old_order = test_billing.new_order(packages, key="historical", slug="starter")
    test_billing.apply(packages, test_billing.notification(packages, old_order))
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
        historical = db.get(BillingOrder, old_order)
        old_price_id = historical.price_version_id
        db.get(SystemLimits, 1).breaker = True
        reviewed_fixture = proposal()
        reviewed_fixture["release_status"] = "ready"
        for name in ("creator", "pro"):
            reviewed_fixture["plans"][name].pop("review_only")
        rows = install(db, config, users["admin"], reviewed_fixture)
        users["prices"].update({r["slug"]: UUID(r["price_version_id"]) for r in rows})
        assert {p.slug for p in plans(db)} == {"free", "creator", "pro"}
        historical = db.get(BillingOrder, old_order)
        assert historical.price_version_id == old_price_id
        assert (historical.amount_paisa, historical.credits) == (29900, 500)
        assert db.get(PlanPrice, old_price_id).price_paisa == 29900
        assert credits.lock_wallet(db, users["alice"]).available == 500
        assert credits.active_price(db, users["alice"]).id == old_price_id
        assert credits.lock_wallet(db, users["bob"]).available == 0
        db.get(SystemLimits, 1).breaker = False
        db.commit()
    order = test_billing.new_order(packages, key="new-proposal-purchase", slug=slug, owner="bob")
    notification = test_billing.notification(packages, order)
    assert test_billing.apply(packages, notification) == "PAID"
    assert test_billing.apply(packages, notification) == "PAID"
    with factory() as db:
        assert (db.get(BillingOrder, order).amount_paisa, db.get(BillingOrder, order).credits) == (
            paisa,
            amount,
        )
        assert credits.lock_wallet(db, users["bob"]).available == amount
        quote = credits.make_quote(
            db, users["bob"], QuoteInput(source_seconds=7200, output_count=1), "duration-quote"
        )
        assert quote.credits == 602
        reservation = credits.reserve(db, users["bob"], quote.id, uuid4(), "duration-hold")
        assert credits.lock_wallet(db, users["bob"]).available == amount - 602
        credits.finish(
            db,
            users["bob"],
            reservation.id,
            "release",
            success=False,
            evidence="fictional-test-failure",
        )
        assert credits.lock_wallet(db, users["bob"]).available == amount
        assert credits.lock_wallet(db, users["alice"]).available == 500
