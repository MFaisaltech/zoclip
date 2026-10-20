"""Review arithmetic and entitlement/capacity boundaries; no paid calls or DB."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from scripts import final_pricing_review as review


@pytest.fixture(scope="module")
def result():
    return json.loads(json.dumps(review.report(), default=str))


def test_replay_and_no_activation(result):
    assert result == json.loads(
        Path("docs/evidence/final-pricing-review-20261020.json").read_text()
    )
    assert result["activation_allowed"] is False
    assert result["certified"] is False
    assert result["pricing_rules_changed"] is False
    assert result["default_deepgram_usd"] == "0"


def test_customers_jobs_outputs_and_capacity_are_distinct(result):
    rows = result["workloads"]
    assert len(rows) == 9
    for row in rows:
        assert row["jobs_month"] == row["customers"] * row["jobs_per_customer"]
        assert row["initial_clips_month"] == row["jobs_month"] * row["outputs"]
        if row["workload"] == "high":
            assert row["within_projected_capacity"] is False
        else:
            assert row["within_projected_capacity"] is True


def test_fixed_pool_reconciles_once_and_no_per_render_api_bill():
    a = review.cost(5, 1, 0, 35, 20, "expected")
    b = review.cost(5, 3, 1, 35, 20, "expected")
    assert a == b  # physical queue cost changes; no metered local-CPU invoice
    assert abs(a["hosting_and_monthly_reserves_usd"] * 700 - 12) < D("1e-24")
    assert a["retry_failure_reserve_usd"] == a["gemini_usd"] * D("0.25")
    assert review.resources(5, 3, 1)["render_seconds"] == 4 * 260
    assert review.quote(5, 1) == review.quote(10, 3, 1) == 60
    assert review.quote(30, 1) == 152 and review.quote(120, 1) == 602


def test_financial_maxima_and_fee_sensitivity(result):
    for profile in result["ceilings"].values():
        for customer_case in profile.values():
            for name in ("creator", "pro"):
                row = customer_case[name]
                cap = row["financial_credit_ceiling"]
                rate = D(row["variable_cost_per_credit_usd"])
                budget = D(row["financial_budget_after_pool_usd"])
                assert cap * rate <= budget < (cap + 1) * rate
                assert row["single_host_all_same_plan_credit_ceiling"] <= cap
    for name in ("creator", "pro"):
        caps = [r[name]["financial_credit_ceiling"] for r in result["fee_sensitivity"].values()]
        assert caps == sorted(caps, reverse=True) and len(set(caps)) == 4


def test_original_credits_cash_viable_but_require_unimplemented_capacity(result):
    for row in result["original_allocation_scaling"]:
        assert D(row["margin"]) >= review.TARGET
        assert row["projected_hosts_required"] > 1
        assert row["implemented"] is False
    stressed = result["ceilings"]["conservative"]["20"]
    assert stressed["creator"]["financial_credit_ceiling"] < 3700
    assert stressed["pro"]["financial_credit_ceiling"] < 9500
    # Current-host fallback fits 50 all-Pro accounts, not just an optimistic mix.
    assert (
        1100
        < result["ceilings"]["high_usage"]["50"]["pro"]["single_host_all_same_plan_credit_ceiling"]
    )
