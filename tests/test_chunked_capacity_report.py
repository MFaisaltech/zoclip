"""Throughput never replaces duration/deadline or commercial acceptance."""

from scripts.chunked_capacity_report import report


def measured():
    phases = [
        {
            "minutes": 5,
            "stage": "concurrent_90s_render",
            "result": "PASS",
            "wall_seconds": 60,
            "process_peak_rss_kib": 1000000,
        }
    ]
    results = []
    files = []
    for m in (5, 30, 120):
        results.append({"minutes": m, "state": "COMPLETED", "local_receipt_bytes": m * 1000})
        files.append({"minutes": m, "bytes": m * 20_000_000})
        for _i in range((m + 1) // 2):
            phases.extend(
                {
                    "minutes": m,
                    "stage": stage,
                    "result": "PASS",
                    "wall_seconds": seconds,
                    "process_peak_rss_kib": 1000000,
                }
                for stage, seconds in (("worker_claim", 60), ("local_whisper", 50))
            )
        phases.append(
            {
                "minutes": m,
                "stage": "captioned_render",
                "result": "PASS",
                "wall_seconds": 20,
                "process_peak_rss_kib": 1000000,
            }
        )
    return {
        "acceptance": {
            "results": results,
            "phases": phases,
            "concurrent_pressure": {"result": "PASS", "output_bytes": 16_000_000},
        },
        "manifest": {"files": files},
        "existing_retained_bytes": 229098014,
        "host_resources": {
            "minimum_available_memory_bytes": 5 * 1024**3,
            "minimum_disk_free_bytes": 50 * 1024**3,
        },
    }


def test_measured_profile_storage_dominates_and_full_redemption_is_not_certified():
    r = report(measured())
    assert r["all_duration_pipeline_pass"]
    assert [p["jobs_month"] for p in r["profiles"]] == sorted(
        [p["jobs_month"] for p in r["profiles"]], reverse=True
    )
    assert all(p["storage_jobs_month"] == p["jobs_month"] for p in r["profiles"])
    assert not r["pricing_activation_allowed"]
    assert all(not s["fits_profile"] for s in r["scenarios"] if s["redemption"] == "high")
    assert r["maximum_size_storage_bound_jobs_month"] == 33


def test_failed_duration_or_deadline_cannot_receive_positive_capacity():
    e = measured()
    e["acceptance"]["results"][-1]["state"] = "FAILED"
    assert report(e)["profiles"][-1]["jobs_month"] is None
    e = measured()
    next(
        p for p in e["acceptance"]["phases"] if p["stage"] == "local_whisper" and p["minutes"] == 30
    )["wall_seconds"] = 301
    r = report(e)
    assert not r["all_duration_pipeline_pass"]
    assert r["profiles"][1]["jobs_month"] is None
    assert not r["pricing_activation_allowed"]


def test_retained_pool_already_full_cannot_be_oversold():
    e = measured()
    e["existing_retained_bytes"] = 40 * 1024**3
    assert all(p["jobs_month"] == 0 for p in report(e)["profiles"])
    assert report(e)["maximum_size_storage_bound_jobs_month"] == 0


def test_ram_headroom_and_missing_host_evidence_fail_closed():
    e = measured()
    next(p for p in e["acceptance"]["phases"] if p["minutes"] == 120)["process_peak_rss_kib"] = (
        2_200_000
    )
    assert report(e)["profiles"][-1]["jobs_month"] is None
    e = measured()
    del e["host_resources"]
    assert all(p["jobs_month"] is None for p in report(e)["profiles"])


def test_existing_backup_guard_reserves_two_envelopes_without_changing_prices():
    e = measured()
    baseline = report(e)["profiles"][0]["jobs_month"]
    e.update(
        post_cleanup_disk_free_bytes=60 * 1024**3,
        live_database_bytes=20 * 1024**2,
        backup_retention_configured=False,
    )
    r = report(e)
    assert r["profiles"][0]["jobs_month"] < baseline
    assert r["profiles"][0]["jobs_month"] == r["profiles"][0]["backup_envelope_jobs_month"]
    from decimal import Decimal as D

    new_live = D(r["backup_envelope_new_retained_bytes"])
    assert D(e["post_cleanup_disk_free_bytes"]) - new_live >= D(20 * 1024**3) + 2 * (
        new_live + e["existing_retained_bytes"] + e["live_database_bytes"]
    )
    assert r["certified_sustainable_monthly_capacity"] is None
    assert not r["backup_retention_configured"] and not r["pricing_activation_allowed"]


def test_recovered_attempt_cost_is_counted_without_claiming_successful_deadline_overrun():
    e = measured()
    e["acceptance"]["phases"].extend(
        {
            "minutes": 120,
            "stage": stage,
            "result": result,
            "wall_seconds": seconds,
            "process_peak_rss_kib": 1000000,
        }
        for stage, result, seconds in (
            ("local_whisper", "FAIL", 308),
            ("worker_claim", "PASS", 310),
        )
    )
    r = report(e)
    p = r["profiles"][-1]
    assert p["accepted"] and p["recovered_asr_failures"] == 1
    assert p["ai_service_seconds"] == "3890"
    assert not r["pricing_activation_allowed"]
