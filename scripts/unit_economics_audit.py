"""Read-only scenario arithmetic. No DB, environment, network, provider or catalog writes.

Run: uv run python -m scripts.unit_economics_audit > /tmp/audit.json
Numbers are hypotheses, never an authorization or a billing/CostRate configuration.
"""

import json
from decimal import ROUND_FLOOR, Decimal
from functools import cache
from pathlib import Path

from scripts.two_plan_economics import CPU_PER_SOURCE_SECOND
from scripts.two_plan_economics import report as previous_report
from zoclip.ai import selection
from zoclip.ai.providers import gemini_body
from zoclip.ai.schemas import Word
from zoclip.core.config import Settings
from zoclip.credits.schemas import ConsumptionRules, QuoteInput
from zoclip.credits.service import calculate

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
FX = D("277.0572")
TARGET = D("0.60")
VPS = D("13.20")
INPUT_RATE = D("0.00000025")
OUTPUT_RATE = D("0.0000015")


@cache
def gemini_projection(minutes: int, outputs: int = 3) -> dict:
    # Synthetic English density fixture, NOT a transcript or a tokenizer benchmark.
    # Constructing settings directly avoids loading .env or production credentials.
    settings = Settings.model_construct(gemini_model="gemini-3.1-flash-lite")
    words = [
        Word.model_construct(
            word="example",
            punctuated_word="example",
            start=i / 3,
            end=(i + 0.9) / 3,
            confidence=1.0,
            speaker=0,
        )
        for i in range(minutes * 180)
    ]
    bodies = [
        gemini_body(selection.prompt(c, settings, outputs), settings)
        for c in selection.chunks(words, settings)
    ]
    body_bounds = [len(json.dumps(b, ensure_ascii=False).encode()) + 1024 for b in bodies]
    empty_body = gemini_body(selection.prompt([], settings, outputs), settings)
    protocol = len(json.dumps(empty_body, ensure_ascii=False).encode()) + 1024
    # Transcript JSON already escapes control characters. Embedding that JSON as
    # text can at most double its UTF-8 bytes through quote/backslash escaping.
    # Do not mistake the old fixed 2048-byte allowance for a proven schema bound.
    serial_bound = 2 * settings.ai_chunk_bytes + protocol
    # bytes/4 is a forecast ONLY; actual admission always uses full byte bounds.
    planning_input = sum(D(n) / 4 for n in body_bounds)
    return {
        "requests": len(bodies),
        "input_byte_admission_units": sum(body_bounds),
        "planning_input_tokens": str(planning_input),
        "planning_output_tokens": len(bodies) * 512,
        "planning_usd": str(planning_input * INPUT_RATE + len(bodies) * 512 * OUTPUT_RATE),
        "actual_body_admission_usd": str(
            sum(body_bounds) * INPUT_RATE + len(bodies) * 2048 * OUTPUT_RATE
        ),
        "global_32_chunk_example_envelope_usd": str(
            32 * ((16000 + 2048) * INPUT_RATE + 2048 * OUTPUT_RATE)
        ),
        "safe_serialization_input_units_per_request": serial_bound,
        "safe_32_chunk_serialization_usd": str(
            32 * (serial_bound * INPUT_RATE + 2048 * OUTPUT_RATE)
        ),
        "measured_tokens": None,
    }


@cache
def quote(minutes: int, outputs: int, edits: int = 0) -> int:
    active = json.loads((ROOT / "deploy/staging-catalog.json").read_text())
    rules = ConsumptionRules.model_validate(active["plans"]["creator"]["rules"])
    return calculate(
        QuoteInput(source_seconds=minutes * 60, output_count=outputs, edit_count=edits), rules
    )


def job_cost(
    minutes: int, outputs: int, edits: int, *, profile: str, monthly_reference_jobs: int = 100
) -> dict:
    if profile not in {"planning", "risk"} or monthly_reference_jobs < 1:
        raise ValueError("Known profile and positive reference volume required")
    # Keep previous 520 CPU-second render envelope; no invented faster FFmpeg benchmark.
    # Allocate the SAME VPS bill once by CPU-equivalent workload, not CPU price + bill.
    reference_work = CPU_PER_SOURCE_SECOND * 300 + D(520 + 10)
    work = CPU_PER_SOURCE_SECOND * minutes * 60 + D(520 * (outputs + edits) + 2 * minutes)
    equivalent_jobs = work / reference_work
    hosting = VPS * equivalent_jobs / monthly_reference_jobs
    # Counts 1..3 occupy the same byte length in the current prompt. Keep the
    # shared three-candidate forecast, not an invented per-output API call.
    gemini = gemini_projection(minutes)
    external = D(
        gemini["planning_usd"]
        if profile == "planning"
        else gemini["safe_32_chunk_serialization_usd"]
    )
    # Risk scenario assumes ADDITIONAL billed copies/transfer, not charges for local SSD.
    # Contract/retention/download assumptions are unverified and not hard upper bounds.
    extra_storage = (
        (D(4 * 1024**3) / 10**9 + D(outputs + edits) * D("0.268435456")) * 7 * D("0.01")
        if profile == "risk"
        else D(0)
    )
    extra_bandwidth = (
        D(outputs + edits) * D("0.268435456") * 3 * D("0.02") if profile == "risk" else D(0)
    )
    base = hosting + external + extra_storage + extra_bandwidth
    multiplier = D("1.25") if profile == "planning" else D("1.50")
    return {
        "minutes": minutes,
        "outputs": outputs,
        "edits": edits,
        "quote_credits": quote(minutes, outputs, edits),
        "projected_cpu_seconds": str(work),
        "reference_job_equivalents": str(equivalent_jobs),
        "hosting_allocation_usd": str(hosting),
        "gemini_usd": str(external),
        "additional_billed_storage_scenario_usd": str(extra_storage),
        "additional_billed_bandwidth_scenario_usd": str(extra_bandwidth),
        "single_risk_reserve_usd": str(base * (multiplier - 1)),
        "total_usd": str(base * multiplier),
        "cost_per_credit_usd": str(base * multiplier / quote(minutes, outputs, edits)),
        "certified": False,
    }


def package(
    price: int,
    worst_cost_per_credit: Decimal,
    *,
    fee: Decimal = D("0.05"),
    fixed_usd: Decimal = D("0.05"),
    fx: Decimal = FX,
) -> dict:
    if not D(0) <= fee < 1 or fixed_usd < 0 or fx <= 0 or worst_cost_per_credit <= 0:
        raise ValueError("Invalid financial inputs")
    gross = D(price) / fx
    net = gross * (1 - fee) - fixed_usd
    allowance = max(D(0), net - gross * TARGET)
    ceiling = int((allowance / worst_cost_per_credit).to_integral_value(rounding=ROUND_FLOOR))
    # Round a review candidate DOWN to 60-credit blocks, with no active term changes.
    candidate = ceiling // 60 * 60
    return {
        "price_pkr": price,
        "gross_usd": str(gross),
        "after_gateway_usd": str(net),
        "maximum_processing_cost_usd": str(allowance),
        "conditional_credit_ceiling": ceiling,
        "rounded_review_candidate": candidate,
        "candidate_worst_margin": str((net - candidate * worst_cost_per_credit) / gross),
        "five_minute_one_output_jobs": candidate // quote(5, 1),
        "five_minute_three_output_jobs": candidate // quote(5, 3),
        "five_minute_three_output_clips": 3 * (candidate // quote(5, 3)),
        "thirty_minute_one_output_jobs": candidate // quote(30, 1),
        "two_hour_one_output_jobs": candidate // quote(120, 1),
        "certified": False,
    }


def report() -> dict:
    previous = previous_report()
    profiles = {}
    for profile in ("planning", "risk"):
        scenarios = [
            job_cost(m, n, e, profile=profile)
            for m in range(1, 121)
            for n in range(1, 4)
            for e in range(2)
        ]
        worst = max(scenarios, key=lambda s: D(s["cost_per_credit_usd"]))
        rate = D(worst["cost_per_credit_usd"])
        profiles[profile] = {
            "monthly_reference_job_equivalents": 100,
            "worst_quoted_scenario": worst,
            "representative_jobs": [
                job_cost(m, n, 0, profile=profile) for m in (5, 30, 120) for n in (1, 3)
            ],
            "packages": {
                name: package(price, rate) for name, price in (("creator", 2000), ("pro", 5000))
            },
            "gateway_sensitivity": {
                str(f): {
                    name: package(p, rate, fee=f) for name, p in (("creator", 2000), ("pro", 5000))
                }
                for f in (D(0), D("0.03"), D("0.05"), D("0.10"))
            },
        }
    volume = {}
    for jobs in (100, 500, 1000):
        scenarios = [
            job_cost(m, n, e, profile="planning", monthly_reference_jobs=jobs)
            for m in range(1, 121)
            for n in range(1, 4)
            for e in range(2)
        ]
        rate = max(D(s["cost_per_credit_usd"]) for s in scenarios)
        volume[str(jobs)] = {
            name: package(p, rate) for name, p in (("creator", 2000), ("pro", 5000))
        }
    return {
        "audit_date": "2026-10-20",
        "activation_allowed": False,
        "certified_allocation": None,
        "measured_scenario": {
            "total_job_cost": None,
            "sustainable_credits": None,
            "local_deepgram_api_charge_usd": "0",
            "reason": (
                "No measured full-job tokens/render/capacity, invoice or merchant fee evidence"
            ),
        },
        "fx": {
            "pkr_per_usd": str(FX),
            "effective_date": "2026-10-16",
            "checked_date": "2026-10-20",
            "kind": "SBP weighted average offer, dated reference, not card settlement",
            "source": "https://www.sbp.org.pk/",
            "previous_assumption": "300",
        },
        "target_gross_revenue_margin": str(TARGET),
        "gemini_list_pricing_source": "https://ai.google.dev/gemini-api/docs/pricing",
        "gemini_synthetic_forecasts": {str(m): gemini_projection(m) for m in (5, 30, 120)},
        "original_five_minute_breakdown": previous["profiles"]["planning"]["creator"]["scenarios"][
            0
        ],
        "previous_ceiling_comparison": {
            k: {name: v["conditional_max_credits_for_target"] for name, v in values.items()}
            for k, values in previous["profiles"].items()
        },
        "profiles": profiles,
        "planning_volume_sensitivity": volume,
        "unverified": [
            "VPS invoice/taxes/traffic/overage",
            "Gemini account pricing/configured model",
            "real token usage/language distribution",
            "FFmpeg representative CPU/RAM/time/size",
            "production volume and workload mix",
            "failure rate and failed-job costs",
            "merchant fees/taxes/FX spread/refunds",
            "off-server backup and operating labor",
            "download volume has no enforced count cap",
            "30/120-minute completion",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
