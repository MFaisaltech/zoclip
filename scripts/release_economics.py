"""Offline scenario estimates only. Never configures budgets, packages or payments."""

import argparse
import json
from decimal import Decimal
from math import ceil
from pathlib import Path


def calculate(config: dict, source_minutes: int, outputs: int, plan: str = "creator") -> dict:
    def d(key: str) -> Decimal:
        return Decimal(str(config[key]))

    if source_minutes not in range(1, 121) or outputs not in range(1, 4):
        raise ValueError("Scenario exceeds configured source/output limits")
    catalog = json.loads(
        (Path(__file__).resolve().parents[1] / "deploy/staging-catalog.json").read_text()
    )
    terms = catalog["plans"][plan]
    rules = terms["rules"]
    credits = max(
        rules["minimum_job_credits"],
        source_minutes * rules["credits_per_minute"] + outputs * rules["credits_per_output"],
    )
    unit_pkr = Decimal(terms["price_paisa"]) / 100 / Decimal(terms["included_credits"])
    # Allocate package revenue pro rata, including bonus credits. No invented price per credit.
    revenue = Decimal(credits) * unit_pkr / d("assumed_pkr_per_usd")
    transcription = Decimal(source_minutes) * d("deepgram_minute_usd")
    # Conservative token upper bound: UTF-8 serialized bytes + schema allowance,
    # for EVERY allowed chunk, including bounded repeated analysis attempts.
    per_chunk = (d("chunk_bytes") + d("protocol_bytes")) * d("gemini_input_token_usd") + d(
        "max_output_tokens"
    ) * d("gemini_output_token_usd")
    # Planning estimate for compact 5-second timed text groups. Byte-as-token
    # accounting remains conservative; runtime admission measures exact bodies.
    text_bytes = (
        source_minutes * int(config["words_per_minute"]) * int(config["utf8_bytes_per_word"])
    )
    segment_bytes = source_minutes * 12 * int(config["bytes_per_segment_metadata"])
    planned_chunks = max(
        1, ceil(Decimal(text_bytes + segment_bytes) * Decimal("1.1") / d("chunk_bytes"))
    )
    analysis = Decimal(min(planned_chunks, int(config["max_chunks"]))) * per_chunk
    maximum_analysis = d("max_chunks") * per_chunk
    compute = (
        Decimal(outputs) * d("render_cpu_seconds_per_output")
        + Decimal(source_minutes) * d("extraction_cpu_seconds_per_minute")
    ) * d("cpu_second_usd")
    storage = (
        Decimal(outputs) * d("storage_gb_days_per_output")
        + Decimal(source_minutes) * d("source_gb_per_minute") * d("source_retention_days")
    ) * d("storage_gb_day_usd")
    bandwidth = Decimal(outputs) * d("output_gb") * d("downloads_per_clip") * d("bandwidth_gb_usd")
    base = transcription + analysis + compute + storage + bandwidth
    risk = base * d("retry_multiplier")
    # Fixed fees occur per package purchase, not per generated clip/job.
    fees = revenue * d("assumed_payment_fee_fraction") + (
        d("assumed_fixed_fee_usd") * Decimal(credits) / Decimal(terms["included_credits"])
    )
    vps_allocation = d("monthly_vps_usd") / d("assumed_monthly_completed_jobs")
    contribution = revenue - risk - fees - vps_allocation
    fraction = contribution / revenue if revenue else Decimal(0)
    target = d("target_contribution_fraction")
    return {
        "source_minutes": source_minutes,
        "plan": plan,
        "package_unit_pkr_per_credit": str(unit_pkr),
        "covered_by_one_package": credits <= terms["included_credits"],
        "outputs": outputs,
        "credits": credits,
        "retail_revenue_usd_estimate": str(revenue),
        "transcription_usd_estimate": str(transcription),
        "planned_analysis_chunks": planned_chunks,
        "analysis_usd_estimate": str(analysis),
        "maximum_analysis_usd_before_retry_multiplier": str(maximum_analysis),
        "render_usd_estimate": str(compute),
        "storage_usd_estimate": str(storage),
        "bandwidth_usd_estimate": str(bandwidth),
        "cost_with_retries_usd_estimate": str(risk),
        "base_operating_cost_usd_estimate": str(base),
        "contribution_before_retry_reserve_usd_estimate": str(
            revenue - base - fees - vps_allocation
        ),
        "payment_fee_usd_estimate": str(fees),
        "payment_fixed_fee_allocation": "pro rata share of one package purchase",
        "vps_allocation_usd_estimate": str(vps_allocation),
        "contribution_fraction_estimate": str(fraction),
        "contribution_usd_estimate": str(contribution),
        "target_met": fraction >= target,
        "max_job_cost_for_target_usd": str(
            max(Decimal(0), revenue * (1 - target) - fees - vps_allocation)
        ),
        "activation": "BLOCKED: account rates, usage, FX and fees remain assumptions",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "kind": "estimates, not measured provider invoices",
                "assumptions": config,
                "scenarios": [
                    calculate(config, m, n, plan)
                    for plan in ("starter", "creator", "pro")
                    for m in (1, 5, 30, 120)
                    for n in (1, 3)
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
