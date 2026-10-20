"""Conservative synthetic throughput after bounded transcription; no activation."""

import json
from decimal import ROUND_FLOOR
from decimal import Decimal as D
from pathlib import Path


def report(evidence: dict) -> dict:
    acceptance = evidence["acceptance"]
    phases = acceptance["phases"]
    cases = {c["minutes"]: c for c in acceptance["results"]}
    pressure = acceptance.get("concurrent_pressure", {})
    pool = max(D(0), D(40 * 1024**3 - evidence.get("existing_retained_bytes", 0)))
    # Existing backup.py requires 20GiB free +2*(media+DB) before creating
    # encrypted files. Include the new live media itself as a third disk share.
    free = evidence.get("post_cleanup_disk_free_bytes")
    live_db = evidence.get("live_database_bytes")
    backup_pool = None
    if free is not None and live_db is not None:
        backup_pool = max(
            D(0),
            (
                D(free)
                - D(20 * 1024**3)
                - 2 * D(evidence.get("existing_retained_bytes", 0) + live_db)
            )
            / 3,
        )
    if backup_pool is not None:
        backup_pool = backup_pool.to_integral_value(rounding=ROUND_FLOOR)
    effective_pool = pool if backup_pool is None else min(pool, backup_pool)
    usable = D(30 * 86400) * D("0.5") / D("1.25")
    resources = evidence.get("host_resources", {})
    host_safe = (
        resources.get("minimum_available_memory_bytes", 0) >= 3 * 1024**3
        and resources.get("minimum_disk_free_bytes", 0) >= 20 * 1024**3
    )
    rss_limit_kib = (
        D(evidence.get("ai_worker_memory_limit_bytes", 2560 * 1024**2)) / 1024 * D("0.80")
    )
    profiles = []
    for minutes in (5, 30, 120):
        case = cases.get(minutes)
        if not case or case["state"] != "COMPLETED" or pressure.get("result") != "PASS":
            profiles.append({"minutes": minutes, "accepted": False, "jobs_month": None})
            continue

        def wall(stage: str, minutes: int = minutes) -> D:
            return sum(
                (
                    D(str(p["wall_seconds"]))
                    for p in phases
                    if p["minutes"] == minutes and p["stage"] == stage and p["result"] == "PASS"
                ),
                D(0),
            )

        claims = [
            p["wall_seconds"]
            for p in phases
            if p["minutes"] == minutes and p["stage"] == "worker_claim"
        ]
        local = [
            p["wall_seconds"]
            for p in phases
            if p["minutes"] == minutes and p["stage"] == "local_whisper" and p["result"] == "PASS"
        ]
        rss = max(p["process_peak_rss_kib"] for p in phases if p["minutes"] == minutes)
        if (
            not claims
            or not local
            or max(claims) >= 660
            or max(local) >= 300
            or not host_safe
            or D(rss) > rss_limit_kib
        ):
            profiles.append(
                {
                    "minutes": minutes,
                    "accepted": False,
                    "jobs_month": None,
                    "blocker": "missing/failed deadline or RAM/disk headroom evidence",
                }
            )
            continue
        source = next(f for f in evidence["manifest"]["files"] if f["minutes"] == minutes)
        render = (
            next(
                D(str(p["wall_seconds"]))
                for p in phases
                if p["stage"] == "concurrent_90s_render" and p["result"] == "PASS"
            )
            * 4
        )
        ai = max(
            wall("local_whisper") + wall("audio_extraction"),
            wall("worker_claim") - wall("captioned_render"),
        )
        retained = (
            source["bytes"] + pressure["output_bytes"] * 4 + case.get("local_receipt_bytes", 0)
        )
        disk = int(pool / (D(retained) * 7 / 30))
        backup_disk = None if backup_pool is None else int(effective_pool / (D(retained) * 7 / 30))
        worker = int(usable / max(ai, render))
        profiles.append(
            {
                "minutes": minutes,
                "accepted": True,
                "jobs_month": min(disk, worker)
                if backup_disk is None
                else min(disk, worker, backup_disk),
                "backup_envelope_jobs_month": backup_disk,
                "storage_jobs_month": disk,
                "worker_jobs_month": worker,
                "retained_bytes_per_job": retained,
                "ai_service_seconds": str(ai),
                "four_90s_render_seconds": str(render),
                "max_claim_wall_seconds": max(
                    p["wall_seconds"]
                    for p in phases
                    if p["minutes"] == minutes and p["stage"] == "worker_claim"
                ),
                "recovered_asr_failures": sum(
                    p["minutes"] == minutes
                    and p["stage"] == "local_whisper"
                    and p["result"] != "PASS"
                    for p in phases
                ),
                "peak_rss_kib": max(
                    p["process_peak_rss_kib"] for p in phases if p["minutes"] == minutes
                ),
            }
        )
    scenarios = []
    for customers in (20, 35, 50):
        creators, pros = (customers + 1) // 2, customers // 2
        for name, fraction in (("low", D("0.1")), ("average", D("0.35")), ("high", D(1))):
            for profile in profiles:
                minutes = profile["minutes"]
                quote = max(60, minutes * 5 + 3 * 2 + 1 * 2)
                jobs = creators * int(D(3700) * fraction / quote) + pros * int(
                    D(9500) * fraction / quote
                )
                scenarios.append(
                    {
                        "customers": customers,
                        "redemption": name,
                        "source_minutes": minutes,
                        "jobs_month": jobs,
                        "fits_profile": profile["jobs_month"] is not None
                        and jobs <= profile["jobs_month"],
                    }
                )
    # Static maximum-size storage bound, not a CPU/quality certification for all formats.
    worst_bytes = 4 * 1024**3 + 4 * evidence.get("render_max_bytes", 256 * 1024**2) + 16 * 1024**2
    return {
        "synthetic_only": True,
        "host_headroom_pass": host_safe,
        "rss_threshold_kib": str(rss_limit_kib),
        "pricing_activation_allowed": False,
        "certified_sustainable_monthly_capacity": None,
        "backup_envelope_new_retained_bytes": str(backup_pool) if backup_pool is not None else None,
        "backup_retention_configured": evidence.get("backup_retention_configured", False),
        "all_duration_pipeline_pass": all(p["accepted"] for p in profiles),
        "profiles": profiles,
        "scenarios": scenarios,
        "maximum_size_storage_bound_jobs_month": int(effective_pool / (D(worst_bytes) * 7 / 30)),
        "assumptions": [
            "7d uniform retention; 40GiB media pool minus existing retained sources",
            "50% usable time, 25% retry-work provision",
            "3x90s outputs plus one edit render projected from measured pressure render",
            "Local chunk receipt bytes retained; DB allocation measured separately",
            "5/30m use SimpleWorker; 120m uses production RQ fork and cold model per chunk",
            "Synthetic acceptance does not certify natural footage or every accepted format",
            "Queue admission rejects bursts; monthly average does not guarantee admission",
            "One future backup reserved; indefinite local archives cannot be certified",
        ],
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(report(json.loads(Path(sys.argv[1]).read_text())), indent=2))
