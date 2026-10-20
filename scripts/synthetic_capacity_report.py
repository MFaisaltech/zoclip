"""Pure measured-fixture capacity/economics sensitivity; never activates pricing."""

import json
import sys
from decimal import ROUND_FLOOR, Decimal

D = Decimal


def report(evidence: dict, *, fx: Decimal = D("277.0572"), fee: Decimal = D("0.02")) -> dict:
    if fx <= 0 or not D(0) <= fee < 1:
        raise ValueError("Positive FX and valid fee required")
    result = evidence["acceptance"]
    cases = {c["minutes"]: c for c in result["results"]}
    phases = result["phases"]
    five = cases.get(5)
    cap = None
    breakdown = None
    if (
        five
        and five["state"] == "COMPLETED"
        and result.get("concurrent_pressure", {}).get("result") == "PASS"
    ):

        def wall(stage):
            return max(
                D(str(p["wall_seconds"]))
                for p in phases
                if p["minutes"] == 5 and p["stage"] == stage and p["result"] == "PASS"
            )

        # 50% time available and a 25% failed/retry workload provision are assumptions.
        usable = D(30 * 24 * 3600) * D("0.50") / D("1.25")
        ai_seconds = wall("audio_extraction") + wall("local_whisper")
        render_seconds = wall("concurrent_90s_render") * 4
        source = next(x for x in evidence["manifest"]["files"] if x["minutes"] == 5)
        retained_per_job = D(source["bytes"] + 4 * result["concurrent_pressure"]["output_bytes"])
        cpu_ceiling = usable / max(ai_seconds, render_seconds)
        retained_pool = max(D(0), D(40 * 1024**3) - D(evidence.get("existing_retained_bytes", 0)))
        disk_ceiling = retained_pool / (retained_per_job * 7 / 30)
        cap = int(min(cpu_ceiling, disk_ceiling).to_integral_value(rounding=ROUND_FLOOR))
        breakdown = {
            "ai_seconds": str(ai_seconds),
            "four_90s_renders_seconds": str(render_seconds),
            "retained_bytes_per_job": str(retained_per_job),
            "worker_ceiling_jobs_month": int(cpu_ceiling),
            "seven_day_storage_ceiling_jobs_month": int(disk_ceiling),
            "assumptions": "4 renders, 7d uniform retention, 50% usable time, 25% retry work",
            "measured_all_four_renders": False,
            "existing_retained_bytes": evidence.get("existing_retained_bytes", 0),
        }
    # Real request admission units from disposable spend attempts; mock usage tokens
    # are fictional and never substituted for actual billed provider consumption.
    input_units = D(evidence.get("gemini_input_admission_units", 0))
    output_units = D(evidence.get("gemini_output_admission_units", 0))
    api_envelope = input_units * D("0.00000025") + output_units * D("0.0000015")
    if api_envelope <= 0:
        api_envelope = None
    scenarios = []
    for customers in (20, 35, 50):
        creators = (customers + 1) // 2
        pros = customers // 2
        revenue = D(creators * 2000 + pros * 5000) / fx
        for label, fraction in (("low", D("0.10")), ("average", D("0.35")), ("high", D(1))):
            creator_jobs = int((D(3700) * fraction / 60).to_integral_value(rounding=ROUND_FLOOR))
            pro_jobs = int((D(9500) * fraction / 60).to_integral_value(rounding=ROUND_FLOOR))
            jobs = creators * creator_jobs + pros * pro_jobs
            cost = D(12) + api_envelope * D("1.25") * jobs if api_envelope else None
            margin = 1 - fee - cost / revenue if cost is not None else None
            scenarios.append(
                {
                    "customers": customers,
                    "creator_customers": creators,
                    "pro_customers": pros,
                    "redemption": label,
                    "fraction": str(fraction),
                    "five_minute_jobs": jobs,
                    "within_projected_five_minute_capacity": cap is not None and jobs <= cap,
                    "monthly_cost_usd": str(cost) if cost is not None else None,
                    "conditional_margin": str(margin) if margin is not None else None,
                    "margin_target_pass": margin is not None and margin >= D("0.60"),
                }
            )
    failing = [m for m in (5, 30, 120) if m not in cases or cases[m]["state"] != "COMPLETED"]
    return {
        "activation_allowed": False,
        "synthetic_only": True,
        "failed_or_missing_minutes": failing,
        "all_duration_pipeline_acceptance": not failing,
        "projected_five_minute_jobs_month": cap,
        "certified_monthly_capacity": None,
        "capacity_breakdown": breakdown,
        "gemini_admission_cost_envelope_usd_per_5min": str(api_envelope) if api_envelope else None,
        "margin_basis": (
            "VPS6+monthly provision6 once; fee field is provisional; "
            "API admission envelope+25%; traffic inclusion conditional"
        ),
        "fx_pkr_usd": str(fx),
        "fee": str(fee),
        "creator": {"price_pkr": 2000, "credits": 3700, "five_minute_jobs": 61},
        "pro": {"price_pkr": 5000, "credits": 9500, "five_minute_jobs": 158},
        "scenarios": scenarios,
        "limitations": [
            "Synthetic repeated motion/speech, not real-world mix",
            "No measured paid tokens/latency; mock receipt usage is fictional",
            "No sustained monthly test or arbitrary-format worst-case guarantee",
            "Cold fork startup and retention bursts need headroom",
            "Financial pass cannot override failed duration or capacity acceptance",
        ],
    }


if __name__ == "__main__":
    from pathlib import Path

    print(json.dumps(report(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))), indent=2))
