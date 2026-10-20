"""Capacity and cash remain separate; never certify synthetic or failed jobs."""

from decimal import Decimal as D

import pytest

from scripts.synthetic_capacity_report import report


def fixture(completed=True):
    return {
        "acceptance": {
            "results": [
                {"minutes": 5, "state": "COMPLETED" if completed else "FAILED"},
                {"minutes": 30, "state": "FAILED"},
                {"minutes": 120, "state": "FAILED"},
            ],
            "phases": [
                {"minutes": 5, "stage": stage, "result": "PASS", "wall_seconds": seconds}
                for stage, seconds in [
                    ("audio_extraction", 10),
                    ("local_whisper", 180),
                    ("concurrent_90s_render", 70),
                ]
            ],
            "concurrent_pressure": {"result": "PASS", "output_bytes": 20_000_000},
        },
        "manifest": {"files": [{"minutes": 5, "bytes": 100_000_000}]},
        "gemini_input_admission_units": 12000,
        "gemini_output_admission_units": 2048,
    }


def test_failed_durations_never_activate_even_when_cash_margin_passes():
    r = report(fixture())
    assert r["failed_or_missing_minutes"] == [30, 120]
    assert not r["activation_allowed"] and r["certified_monthly_capacity"] is None
    assert not r["all_duration_pipeline_acceptance"]
    assert all(s["margin_target_pass"] for s in r["scenarios"])
    assert any(not s["within_projected_five_minute_capacity"] for s in r["scenarios"])
    assert r["creator"]["credits"] == 3700 and r["pro"]["credits"] == 9500


def test_disk_bound_and_customer_job_counts_are_not_conflated():
    r = report(fixture())
    cap = r["projected_five_minute_jobs_month"]
    disk_budget = D(40 * 1024**3)
    per_job = D(180_000_000) * 7 / 30
    assert cap * per_job <= disk_budget < (cap + 1) * per_job
    assert r["scenarios"][-1]["five_minute_jobs"] == 25 * (61 + 158)
    assert not r["scenarios"][-1]["within_projected_five_minute_capacity"]


def test_no_successful_reference_means_no_positive_throughput_claim():
    r = report(fixture(False))
    assert r["projected_five_minute_jobs_month"] is None
    assert all(not s["within_projected_five_minute_capacity"] for s in r["scenarios"])
    with pytest.raises(ValueError):
        report(fixture(), fee=D(1))


def test_pressure_evidence_required_and_existing_storage_reduces_capacity():
    evidence = fixture()
    baseline = report(evidence)["projected_five_minute_jobs_month"]
    evidence["existing_retained_bytes"] = 20 * 1024**3
    assert report(evidence)["projected_five_minute_jobs_month"] < baseline
    del evidence["acceptance"]["concurrent_pressure"]["result"]
    assert report(evidence)["projected_five_minute_jobs_month"] is None


def test_checked_in_measurements_replay_without_claiming_long_job_capacity():
    import json
    from pathlib import Path

    evidence = json.loads(
        (Path(__file__).parents[1] / "docs/evidence/synthetic-capacity-20261020.json").read_text()
    )
    assert report(evidence) == evidence["capacity_model"]
    assert report(evidence)["projected_five_minute_jobs_month"] == 1128
    assert evidence["whisper_120_worker_diagnostic"]["state"]["OOMKilled"]
    assert evidence["preservation"]["all_13_tables_unchanged"]
