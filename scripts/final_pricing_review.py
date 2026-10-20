"""Owner-cost review only: deterministic, offline, no catalog or runtime writes."""

import json
from decimal import ROUND_FLOOR, Decimal
from functools import cache

from scripts.two_plan_economics import CPU_PER_SOURCE_SECOND
from scripts.unit_economics_audit import FX, gemini_projection, quote

D = Decimal
MONTH = D(30 * 24 * 3600)
TARGET = D("0.60")
PACKAGES = [
    ("Old Starter", 299, 500),
    ("Old Creator", 699, 1300),
    ("Old Pro", 1299, 2400),
    ("Original Creator", 2000, 3700),
    ("Original Pro", 5000, 9500),
    ("Previous conservative Creator", 2000, 280),
    ("Previous conservative Pro", 5000, 720),
    ("Single-host fallback Creator", 2000, 440),
    ("Single-host fallback Pro", 5000, 1100),
]
# Explicit forecasts, not measured error rates, contracts or service guarantees.
PROFILES = {
    "expected": dict(pool="12", risk="0.25", traffic="0", utilization="0.50", slowdown="1"),
    "high_usage": dict(pool="24", risk="0.25", traffic="0", utilization="0.50", slowdown="1"),
    "conservative": dict(
        pool="36", risk="0.50", traffic="0.02", utilization="0.35", slowdown="1.25"
    ),
}


def floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def resources(minutes: int, outputs: int, edits: int = 0) -> dict:
    # Single short cold benchmark, linear projection only. RQ startup/extraction/
    # analysis/ingestion are not timed; add 30s to AI service as a planning allowance.
    ai = D("20.70032785") / D("25.14725") * minutes * 60 + 30
    render = D(max(240, 520 // 2)) * (outputs + edits)
    return {
        "ai_seconds": ai,
        "render_seconds": render,
        "cpu_seconds": CPU_PER_SOURCE_SECOND * minutes * 60
        + D(2 * minutes + 520 * (outputs + edits)),
    }


def cost(minutes: int, outputs: int, edits: int, customers: int, jobs: int, profile: str):
    p = PROFILES[profile]
    if customers <= 0 or jobs <= 0:
        raise ValueError("Positive customer/job volume required")
    # Pool is VPS6 + operations/backup/upgrade reserve6/18/30, allocated ONCE.
    host = D(p["pool"]) / (customers * jobs)
    projection = gemini_projection(minutes)
    gemini = D(
        projection["actual_body_admission_usd" if profile == "conservative" else "planning_usd"]
    )
    # Hypothetical additional backup/traffic service, never local SSD CPU pricing.
    extra = D(p["traffic"]) * (1 + outputs + edits)
    variable = gemini + extra
    return {
        "hosting_and_monthly_reserves_usd": host,
        "gemini_usd": gemini,
        "additional_storage_traffic_usd": extra,
        "retry_failure_reserve_usd": variable * D(p["risk"]),
        "total_usd": host + variable * (1 + D(p["risk"])),
    }


def capacity(minutes: int, outputs: int, edits: int, profile: str) -> dict:
    p = PROFILES[profile]
    r = resources(minutes, outputs, edits)
    usable = MONTH * D(p["utilization"])
    factor = (1 + D(p["risk"])) * D(p["slowdown"])
    # Use both worker bottlenecks and total CPU; leaves host headroom by utilization.
    ceiling = min(
        usable / (r["ai_seconds"] * factor),
        usable / (r["render_seconds"] * factor),
        4 * usable / (r["cpu_seconds"] * factor),
        # Forecast: 15MB/source minute, 10MB/render, seven-day uniform retention.
        # 40GiB commitment gate, not all free filesystem space. Scratch is separate.
        D(40 * 1024**3) / 10**9 / ((D("0.015") * minutes + D("0.01") * (outputs + edits)) * 7 / 30),
    )
    return {"projected_jobs_month": floor(ceiling), "measured": False}


def margin(price: int, total: Decimal, fee: Decimal = D("0.02")) -> Decimal:
    revenue = D(price) / FX
    return 1 - fee - total / revenue


@cache
def ceilings(customers: int, profile: str, fee: Decimal = D("0.02")) -> dict:
    # Full redemption: enumerate ALL quoted durations/output/edit combinations.
    # Fixed pool is per customer, not per hypothetical job. Never subtract it twice.
    p = PROFILES[profile]
    worst_money = D(0)
    worst_ai = D(0)
    worst_render = D(0)
    worst_cpu = D(0)
    worst_storage = D(0)
    for m in range(1, 121):
        for n in range(1, 4):
            for e in range(2):
                credits = quote(m, n, e)
                c = cost(m, n, e, customers, 1, profile)
                variable = c["total_usd"] - c["hosting_and_monthly_reserves_usd"]
                worst_money = max(worst_money, variable / credits)
                r = resources(m, n, e)
                worst_ai = max(worst_ai, r["ai_seconds"] / credits)
                worst_render = max(worst_render, r["render_seconds"] / credits)
                worst_cpu = max(worst_cpu, r["cpu_seconds"] / credits)
                worst_storage = max(
                    worst_storage,
                    (D("0.015") * m + D("0.01") * (n + e)) * 7 / 30 / credits,
                )
    factor = (1 + D(p["risk"])) * D(p["slowdown"])
    available = MONTH * D(p["utilization"]) / factor
    total_capacity_credits = min(
        available / worst_ai,
        available / worst_render,
        4 * available / worst_cpu,
        D(40 * 1024**3) / 10**9 / worst_storage,
    )
    result = {}
    for name, price in (("creator", 2000), ("pro", 5000)):
        budget = D(price) / FX * (1 - fee - TARGET) - D(p["pool"]) / customers
        money_cap = max(0, floor(budget / worst_money))
        # All customers on this plan. Independent columns are not an additive pool.
        host_cap = floor(total_capacity_credits / customers)
        result[name] = {
            "financial_credit_ceiling": money_cap,
            "single_host_all_same_plan_credit_ceiling": min(money_cap, host_cap),
            "variable_cost_per_credit_usd": worst_money,
            "financial_budget_after_pool_usd": budget,
        }
    # Joint 2:5 allocation preserves price/credit value, assumes 50:50 paid-plan mix.
    creator = min(
        D(result["creator"]["financial_credit_ceiling"]),
        D(result["pro"]["financial_credit_ceiling"]) / D("2.5"),
        total_capacity_credits / (D(customers) * D("1.75")),
    )
    result["balanced_mix_joint_ceiling"] = {
        "creator": floor(creator),
        "pro": floor(creator * D("2.5")),
    }
    result["total_host_credit_capacity"] = total_capacity_credits
    return result


def report() -> dict:
    workloads = []
    for customers in (20, 35, 50):
        for label, jobs, m, n, e, profile in (
            ("low", 5, 5, 1, 0, "expected"),
            ("medium", 20, 5, 3, 0, "expected"),
            ("high", 60, 10, 3, 1, "high_usage"),
        ):
            r = resources(m, n, e)
            factor = 1 + D(PROFILES[profile]["risk"])
            volume = customers * jobs
            cap = capacity(m, n, e, profile)["projected_jobs_month"]
            workloads.append(
                dict(
                    customers=customers,
                    workload=label,
                    jobs_per_customer=jobs,
                    source_minutes=m,
                    outputs=n,
                    edits=e,
                    jobs_month=volume,
                    initial_clips_month=volume * n,
                    renders_including_edits=volume * (n + e),
                    consumed_credits_per_customer=jobs * quote(m, n, e),
                    ai_busy_hours=r["ai_seconds"] * volume * factor / 3600,
                    render_busy_hours=r["render_seconds"] * volume * factor / 3600,
                    within_projected_capacity=volume <= cap,
                    projected_host_count=(volume + cap - 1) // cap,
                    projected_retained_gb=(D("0.015") * m + D("0.01") * (n + e)) * volume * 7 / 30,
                    projected_ingress_plus_three_downloads_gb=(D("0.015") * m + D("0.03") * (n + e))
                    * volume,
                    job_cost=cost(m, n, e, customers, jobs, profile),
                )
            )
    comparisons = []
    for name, price, credits in PACKAGES:
        jobs = credits // 60
        # Full five-minute redemption, three initial outputs + one prepaid rerender.
        # Allocate pool equally over 20 customers even for legacy plans, same basis.
        c = cost(5, 3, 1, 20, max(1, jobs), "high_usage")
        total = c["total_usd"] * jobs
        comparisons.append(
            dict(
                package=name,
                price_pkr=price,
                credits=credits,
                five_minute_jobs=jobs,
                conditional_initial_clips=jobs * 3,
                renders_with_prepaid_edits=jobs * 4,
                cost_usd=total,
                margin=margin(price, total),
                render_hours_customer=resources(5, 3, 1)["render_seconds"]
                * jobs
                * D("1.25")
                / 3600,
            )
        )
    scaling = []
    for customers in (20, 35, 50):
        for name, price, credits in (("creator", 2000, 3700), ("pro", 5000, 9500)):
            # Worst render entitlement: 60 credits can buy 3 outputs + 1 edit.
            jobs = credits // 60
            cap = capacity(10, 3, 1, "high_usage")["projected_jobs_month"]
            hosts = (customers * jobs + cap - 1) // cap
            pool = D(6 * hosts + 6)  # entire fleet invoice once + $6 operating reserve
            variable_rate = ceilings(customers, "high_usage")[name]["variable_cost_per_credit_usd"]
            total = pool / customers + credits * variable_rate
            scaling.append(
                dict(
                    customers=customers,
                    plan=name,
                    projected_hosts_required=hosts,
                    fleet_and_operations_usd=pool,
                    full_credit_cost_customer_usd=total,
                    margin=margin(price, total),
                    implemented=False,
                )
            )
    return dict(
        date="2026-10-20",
        activation_allowed=False,
        certified=False,
        pricing_rules_changed=False,
        default_deepgram_usd="0",
        owner_vps_range_usd=["5.30", "6"],
        modeled_vps_usd="6",
        fee_assumption="0.02",
        fixed_fee_usd="0",
        fx_pkr_usd=FX,
        fx_status="Prior audit dated 2026-10-16 reference; not refreshed settlement FX",
        profiles=PROFILES,
        workloads=workloads,
        comparisons=comparisons,
        original_allocation_scaling=scaling,
        representative_jobs=[
            dict(
                minutes=m,
                outputs=n,
                edits=e,
                credits=quote(m, n, e),
                projected_resources=resources(m, n, e),
                expected_cost_at_35_customers_20_jobs=cost(m, n, e, 35, 20, "expected"),
                completion_verified=False,
            )
            for m, n, e in [(5, 1, 0), (5, 3, 0), (5, 3, 1), (30, 1, 0), (120, 1, 0)]
        ],
        ceilings={p: {str(n): ceilings(n, p) for n in (20, 35, 50)} for p in PROFILES},
        fee_sensitivity={
            str(f): ceilings(50, "high_usage", f) for f in map(D, ("0.02", "0.05", "0.08", "0.10"))
        },
        capacities={
            p: {
                f"{m}m_{n}out_{e}edit": capacity(m, n, e, p)
                for m, n, e in [(5, 1, 0), (5, 3, 0), (10, 3, 1)]
            }
            for p in PROFILES
        },
    )


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, default=str))
