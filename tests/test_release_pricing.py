"""A minimum charge is configurable, and does not weaken account limits."""

import json
from pathlib import Path

import pytest

from zoclip.core.errors import ApiError
from zoclip.credits.schemas import ConsumptionRules, QuoteInput
from zoclip.credits.service import calculate


def test_minimum_price_applies_to_short_sources_but_preserves_plan_limits():
    terms = json.loads(Path("deploy/staging-catalog.json").read_text())["plans"]["free"]
    rules = ConsumptionRules.model_validate(terms["rules"])
    assert terms["included_credits"] == 60  # Dormant, once-only trial; not an automatic grant.
    assert calculate(QuoteInput(source_seconds=26, output_count=1), rules) == 60
    assert calculate(QuoteInput(source_seconds=300, output_count=1), rules) == 60
    for request in [
        QuoteInput(source_seconds=301, output_count=1),
        QuoteInput(source_seconds=26, output_count=2),
    ]:
        with pytest.raises(ApiError, match="plan_limit"):
            calculate(request, rules)
    with pytest.raises(ApiError, match="plan_limit"):
        calculate(QuoteInput(source_seconds=26, output_count=4), rules)
    assert (
        calculate(
            QuoteInput(source_seconds=26, output_count=1),
            rules.model_copy(update={"minimum_job_credits": 0}),
        )
        == 7
    )


@pytest.mark.parametrize("minutes,outputs", [(1, 1), (5, 3), (30, 3), (120, 3)])
@pytest.mark.parametrize("plan", ["starter", "creator", "pro"])
def test_estimates_use_actual_package_revenue_and_disclose_margin_shortfall(minutes, outputs, plan):
    from scripts.release_economics import calculate as economics

    config = json.loads(Path("deploy/economics.example.json").read_text())
    from decimal import Decimal

    result = economics(config, minutes, outputs, plan)
    terms = json.loads(Path("deploy/staging-catalog.json").read_text())["plans"][plan]
    expected = Decimal(terms["price_paisa"]) / 100 / terms["included_credits"]
    assert Decimal(result["package_unit_pkr_per_credit"]) == expected
    assert Decimal(result["payment_fee_usd_estimate"]) == (
        Decimal(result["retail_revenue_usd_estimate"])
        * Decimal(config["assumed_payment_fee_fraction"])
        + Decimal(config["assumed_fixed_fee_usd"]) * result["credits"] / terms["included_credits"]
    )
    assert not result["target_met"]  # Actual retail prices cannot substantiate the former claim.
    assert result["credits"] == max(60, minutes * 5 + outputs * 2)
    assert result["covered_by_one_package"] == (result["credits"] <= terms["included_credits"])
    assert Decimal(result["maximum_analysis_usd_before_retry_multiplier"]) >= Decimal(
        result["analysis_usd_estimate"]
    )
    assert result["activation"].startswith("BLOCKED")
    # Retail terms never become approved just because an estimate passed.
    plans = json.loads(Path("deploy/staging-catalog.json").read_text())["plans"]
    assert all(not p["approved"] for slug, p in plans.items() if slug != "free")
