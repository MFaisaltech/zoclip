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
    assert terms["included_credits"] == 0
    assert calculate(QuoteInput(source_seconds=26, output_count=1), rules) == 60
    assert calculate(QuoteInput(source_seconds=7200, output_count=3), rules) == 606
    with pytest.raises(ApiError, match="plan_limit"):
        calculate(QuoteInput(source_seconds=26, output_count=4), rules)
    assert (
        calculate(
            QuoteInput(source_seconds=26, output_count=1),
            rules.model_copy(update={"minimum_job_credits": 0}),
        )
        == 7
    )


@pytest.mark.parametrize("minutes,outputs", [(1, 1), (1, 3), (2, 2), (30, 3), (120, 3)])
def test_draft_catalog_covers_conservative_scenarios_at_assumed_rates(minutes, outputs):
    from scripts.release_economics import calculate as economics

    config = json.loads(Path("deploy/economics.example.json").read_text())
    result = economics(config, minutes, outputs)
    assert result["target_met"]
    assert result["activation"].startswith("BLOCKED")
    # Retail terms never become approved just because an estimate passed.
    plans = json.loads(Path("deploy/staging-catalog.json").read_text())["plans"]
    assert all(not p["approved"] for slug, p in plans.items() if slug != "free")
