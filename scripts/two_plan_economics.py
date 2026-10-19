"""Read-only two-package decision report. Never approves a catalog or installs CostRates."""

import json
from decimal import ROUND_FLOOR, Decimal
from math import ceil
from pathlib import Path

from zoclip.credits.schemas import ConsumptionRules, QuoteInput
from zoclip.credits.service import calculate

ROOT = Path(__file__).resolve().parents[1]
PROPOSED = {"creator": (2000, 3700), "pro": (5000, 9500)}
# Measured cold CPU work on the existing VPS; not a long-source benchmark/rate.
CPU_PER_SOURCE_SECOND = Decimal("39.010763") / Decimal("25.14725")


def scenario(
    config: dict, rules: ConsumptionRules, minutes: int, outputs: int, *, envelope: bool = False
) -> dict:
    def d(key: str) -> Decimal:
        return Decimal(str(config[key]))

    credits = calculate(QuoteInput(source_seconds=minutes * 60, output_count=outputs), rules)
    planned = max(
        1,
        ceil(
            Decimal(
                minutes
                * (
                    config["words_per_minute"] * config["utf8_bytes_per_word"]
                    + 12 * config["bytes_per_segment_metadata"]
                )
            )
            * Decimal("1.1")
            / d("chunk_bytes")
        ),
    )
    chunks = int(config["max_chunks"]) if envelope else min(planned, int(config["max_chunks"]))
    gemini = chunks * (
        (d("chunk_bytes") + d("protocol_bytes")) * d("gemini_input_token_usd")
        + d("max_output_tokens") * d("gemini_output_token_usd")
    )
    local_cpu = CPU_PER_SOURCE_SECOND * minutes * 60
    transcription = local_cpu * d("cpu_second_usd")
    render = (
        outputs * d("render_cpu_seconds_per_output")
        + minutes * d("extraction_cpu_seconds_per_minute")
    ) * d("cpu_second_usd")
    # Model source/input retention explicitly, not merely rendered outputs.
    source_gb = Decimal(4 * 1024**3) / 10**9 if envelope else minutes * d("source_gb_per_minute")
    storage = (
        outputs * d("storage_gb_days_per_output") + source_gb * d("source_retention_days")
    ) * d("storage_gb_day_usd")
    bandwidth = outputs * d("output_gb") * d("downloads_per_clip") * d("bandwidth_gb_usd")
    vps = d("monthly_vps_usd") / d("assumed_monthly_completed_jobs")
    base = transcription + gemini + render + storage + bandwidth
    cost = base * d("retry_multiplier") + vps
    return {
        "source_minutes": minutes,
        "outputs": outputs,
        "credits": credits,
        "whisper_cpu_seconds_projected": str(local_cpu),
        "deepgram_api_usd": "0",
        "whisper_allocation_usd": str(transcription),
        "gemini_usd": str(gemini),
        "render_extraction_usd": str(render),
        "storage_usd": str(storage),
        "bandwidth_usd": str(bandwidth),
        "vps_per_job_usd": str(vps),
        "base_components_usd": str(base),
        "risk_adjusted_with_vps_usd": str(cost),
        "cost_per_credit_usd": str(cost / credits),
        "long_source_completion_verified": False,
    }


def report(config: dict | None = None) -> dict:
    config = config or json.loads((ROOT / "deploy/economics.example.json").read_text())
    active = json.loads((ROOT / "deploy/staging-catalog.json").read_text())
    result = {
        "activation_allowed": False,
        "reason": "No verified account-rate/fee evidence or approved active spending policy",
        "target_margin": str(config["target_contribution_fraction"]),
        "assumptions": config,
        "evidence": {
            "gemini_public_text_rates_checked": "2026-10-20",
            "gemini_pricing_source": "https://ai.google.dev/gemini-api/docs/pricing",
            "account_specific_rates_verified": False,
            "merchant_fees_verified": False,
            "whisper_cpu_source": "docs/WHISPER_RELEASE_2026-10-19.md",
            "internal_costrates_changed": False,
            "warning": (
                "CPU/storage/bandwidth allocations and VPS overhead can overlap; not invoices"
            ),
        },
        "profiles": {},
    }
    for name, envelope in [("planning", False), ("bounded_admission_envelope", True)]:
        packages = {}
        for slug, (price_pkr, credits) in PROPOSED.items():
            rules = ConsumptionRules.model_validate(active["plans"][slug]["rules"])
            scenarios = [
                scenario(config, rules, m, n, envelope=envelope)
                for m in range(1, 121)
                for n in range(1, 4)
            ]
            worst = max(scenarios, key=lambda r: Decimal(r["cost_per_credit_usd"]))
            price_usd = Decimal(price_pkr) / Decimal(str(config["assumed_pkr_per_usd"]))
            fee_fraction = Decimal(str(config["assumed_payment_fee_fraction"]))
            fixed = Decimal(str(config["assumed_fixed_fee_usd"]))
            target = Decimal(str(config["target_contribution_fraction"]))
            cost_per_credit = Decimal(worst["cost_per_credit_usd"])
            ceiling = max(
                0,
                int(
                    (
                        (price_usd * (1 - fee_fraction - target) - fixed) / cost_per_credit
                    ).to_integral_value(rounding=ROUND_FLOOR)
                ),
            )
            margin = (
                price_usd * (1 - fee_fraction) - fixed - credits * cost_per_credit
            ) / price_usd
            representative = calculate(QuoteInput(source_seconds=300, output_count=1), rules)
            packages[slug] = {
                "price_pkr": price_pkr,
                "proposed_credits": credits,
                "worst_quoted_scenario": worst,
                "conditional_max_credits_for_target": ceiling,
                "proposed_worst_margin_fraction": str(margin),
                "proposed_passes_assumed_target": margin >= target,
                "representative_source_seconds": 300,
                "representative_outputs_per_job": 1,
                "representative_credits_per_clip": representative,
                "conditional_clip_target": credits // representative,
                "scenarios": [
                    r
                    for r in scenarios
                    if r["source_minutes"] in (5, 30, 120) and r["outputs"] in (1, 3)
                ],
            }
        result["profiles"][name] = packages
    return result


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
