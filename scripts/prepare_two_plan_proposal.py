"""Generate an explicitly non-installable owner proposal, never the active catalog."""

import json
from copy import deepcopy
from pathlib import Path

from zoclip.credits.schemas import ConsumptionRules, QuoteInput
from zoclip.credits.service import calculate

ROOT = Path(__file__).resolve().parents[1]


def proposal() -> dict:
    # Reproduce the dated proposal from its original terms, never today's offers.
    active = json.loads((ROOT / "tests/fixtures/legacy-catalog.json").read_text())
    result = {
        "version": "pricing-20261020-proposal",
        "release_status": "proposal",
        "reason": "Owner two-package proposal; activation blocked by unverified economics",
        "retired": ["starter", "business", "topup"],
        "estimate": {"source_seconds": 300, "outputs_per_job": 1, "edits_per_job": 0},
        "display": {"free": deepcopy(active["display"]["free"])},
        "plans": {"free": deepcopy(active["plans"]["free"])},
    }
    for slug, price, credits in [("creator", 200000, 3700), ("pro", 500000, 9500)]:
        terms = deepcopy(active["plans"][slug])
        terms.update(price_paisa=price, included_credits=credits, approved=False)
        # Older deployed installers do not know the root release_status gate.
        # Their strict PlanVersionInput also rejects this review-only marker.
        terms["review_only"] = True
        # Make the purchased allowance usable within the unchanged prepaid access
        # period; do not carry over the obsolete 2500-credit monthly ceiling.
        terms["rules"]["monthly_credits"] = credits
        quote = calculate(
            QuoteInput(source_seconds=300, output_count=1),
            ConsumptionRules.model_validate(terms["rules"]),
        )
        result["plans"][slug] = terms
        result["display"][slug] = {
            "name": slug.upper(),
            "bonus_credits": 0,
            "target_clips": credits // quote,
            "representative_quote_credits": quote,
        }
    return result


if __name__ == "__main__":
    (ROOT / "deploy/pricing-proposal-20261020.json").write_text(
        json.dumps(proposal(), indent=2) + "\n"
    )
