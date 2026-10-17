"""Offline scenario estimates only. Never configures budgets, packages or payments."""

import argparse
import json
from decimal import Decimal
from pathlib import Path


def calculate(config: dict, source_minutes: int, outputs: int) -> dict:
    def d(key: str) -> Decimal:
        return Decimal(str(config[key]))

    credits = source_minutes * int(config["credits_per_minute"]) + outputs * int(
        config["credits_per_output"]
    )
    credits = max(int(config.get("minimum_job_credits", 0)), credits)
    revenue = Decimal(credits) * d("pkr_per_credit") / d("assumed_pkr_per_usd")
    transcription = Decimal(source_minutes) * d("deepgram_minute_usd")
    # Conservative token upper bound: UTF-8 serialized bytes + schema allowance,
    # for EVERY allowed chunk, including bounded repeated analysis attempts.
    analysis = d("max_chunks") * (
        (d("chunk_bytes") + d("protocol_bytes")) * d("gemini_input_token_usd")
        + d("max_output_tokens") * d("gemini_output_token_usd")
    )
    compute = Decimal(outputs) * d("render_cpu_seconds_per_output") * d("cpu_second_usd")
    storage = Decimal(outputs) * d("storage_gb_days_per_output") * d("storage_gb_day_usd")
    bandwidth = Decimal(outputs) * d("output_gb") * d("downloads_per_clip") * d("bandwidth_gb_usd")
    base = transcription + analysis + compute + storage + bandwidth
    risk = base * d("retry_multiplier")
    fees = revenue * d("assumed_payment_fee_fraction") + d("assumed_fixed_fee_usd")
    vps_allocation = d("monthly_vps_usd") / d("assumed_monthly_completed_jobs")
    contribution = revenue - risk - fees - vps_allocation
    fraction = contribution / revenue
    target = d("target_contribution_fraction")
    return {
        "source_minutes": source_minutes,
        "outputs": outputs,
        "credits": credits,
        "retail_revenue_usd_estimate": str(revenue),
        "transcription_usd_estimate": str(transcription),
        "max_analysis_usd_estimate": str(analysis),
        "render_usd_estimate": str(compute),
        "storage_usd_estimate": str(storage),
        "bandwidth_usd_estimate": str(bandwidth),
        "cost_with_retries_usd_estimate": str(risk),
        "payment_fee_usd_estimate": str(fees),
        "vps_allocation_usd_estimate": str(vps_allocation),
        "contribution_fraction_estimate": str(fraction),
        "target_met": fraction >= target,
        "max_job_cost_for_target_usd": str(
            max(Decimal(0), revenue * (1 - target) - fees - vps_allocation)
        ),
        "activation": "BLOCKED: estimates require measured usage and verified gateway fees",
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
                    calculate(config, m, n) for m, n in [(1, 1), (2, 2), (30, 3), (120, 3)]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
