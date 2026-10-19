"""Pure audit arithmetic; no databases, providers, balances or configuration writes."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import unit_economics_audit as audit


@pytest.fixture(scope="module")
def result():
    return audit.report()


def test_audit_never_certifies_missing_inputs(result):
    assert result["activation_allowed"] is False
    assert result["certified_allocation"] is None
    assert result["measured_scenario"]["total_job_cost"] is None
    assert result["measured_scenario"]["sustainable_credits"] is None
    assert result["previous_ceiling_comparison"] == {
        "planning": {"creator": 191, "pro": 486},
        "bounded_admission_envelope": {"creator": 61, "pro": 155},
    }
    assert result == json.loads(
        Path("docs/evidence/unit-economics-simulation-20261020.json").read_text()
    )


def test_original_estimate_reconciles_exactly(result):
    old = result["original_five_minute_breakdown"]
    base = sum(
        Decimal(old[k])
        for k in [
            "whisper_allocation_usd",
            "gemini_usd",
            "render_extraction_usd",
            "storage_usd",
            "bandwidth_usd",
        ]
    )
    assert abs(base * 3 + Decimal("0.132") - Decimal(old["risk_adjusted_with_vps_usd"])) < Decimal(
        "1e-24"
    )
    assert old["deepgram_api_usd"] == "0"


def test_each_ceiling_is_maximal_and_candidate_preserves_target(result):
    for profile in result["profiles"].values():
        rate = Decimal(profile["worst_quoted_scenario"]["cost_per_credit_usd"])
        assert profile["worst_quoted_scenario"]["edits"] == 1
        for package in profile["packages"].values():
            cap = package["conditional_credit_ceiling"]
            available = Decimal(package["maximum_processing_cost_usd"])
            assert cap * rate <= available < (cap + 1) * rate
            assert package["rounded_review_candidate"] <= cap
            assert Decimal(package["candidate_worst_margin"]) >= audit.TARGET
            assert not package["certified"]


def test_marginal_and_fixed_costs_are_separate_and_edit_is_not_free():
    base = audit.job_cost(5, 1, 0, profile="planning")
    edit = audit.job_cost(5, 1, 1, profile="planning")
    assert base["hosting_allocation_usd"] == "0.132"
    assert Decimal(edit["hosting_allocation_usd"]) > Decimal(base["hosting_allocation_usd"])
    assert edit["gemini_usd"] == base["gemini_usd"]
    assert base["quote_credits"] == edit["quote_credits"] == 60
    assert audit.quote(30, 1) == 152 and audit.quote(120, 1) == 602
    assert audit.quote(5, 3) == 60


def test_more_fees_and_weaker_fx_reduce_allowance_and_volume_is_conditional(result):
    rate = Decimal("0.01")
    assert (
        audit.package(2000, rate, fee=Decimal("0.10"))["conditional_credit_ceiling"]
        < audit.package(2000, rate)["conditional_credit_ceiling"]
    )
    assert (
        audit.package(2000, rate, fx=Decimal(300))["conditional_credit_ceiling"]
        < audit.package(2000, rate)["conditional_credit_ceiling"]
    )
    for profile in result["profiles"].values():
        p = profile["packages"]
        assert (
            Decimal(p["pro"]["conditional_credit_ceiling"]) / 5000
            > Decimal(p["creator"]["conditional_credit_ceiling"]) / 2000
        )
    for slug in ("creator", "pro"):
        caps = [
            result["planning_volume_sensitivity"][str(n)][slug]["conditional_credit_ceiling"]
            for n in (100, 500, 1000)
        ]
        assert caps == sorted(caps) and len(set(caps)) == 3


def test_pure_projection_does_not_dispatch_or_mutate_active_files(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Audit attempted a side effect")

    import socket
    import subprocess

    from zoclip.ai.providers import HTTPProviders, LocalWhisperProviders
    from zoclip.core import db

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(db, "build_engine", forbidden)
    monkeypatch.setattr(HTTPProviders, "request", forbidden)
    monkeypatch.setattr(LocalWhisperProviders, "transcribe", forbidden)
    files = [
        Path("deploy/staging-catalog.json"),
        Path("deploy/economics.example.json"),
        Path("src/zoclip/credits/service.py"),
        Path("src/zoclip/credits/schemas.py"),
    ]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    audit.gemini_projection.cache_clear()
    audit.quote.cache_clear()
    forecast = audit.gemini_projection(5)
    assert int(forecast["requests"]) >= 1
    assert forecast["measured_tokens"] is None
    assert Decimal(forecast["planning_usd"]) <= Decimal(forecast["actual_body_admission_usd"])
    audit.job_cost(5, 3, 1, profile="risk")
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]


def test_serialization_bound_covers_escaped_multibyte_transcript():
    from zoclip.ai import selection
    from zoclip.ai.providers import gemini_body
    from zoclip.ai.schemas import Word
    from zoclip.core.config import Settings

    settings = Settings.model_construct(gemini_model="gemini-3.1-flash-lite")
    value = '\\"\n😀' * 30
    words = [
        Word.model_construct(
            word=value, punctuated_word=value, start=i, end=i + 0.9, confidence=1.0, speaker=0
        )
        for i in range(100)
    ]
    bound = audit.gemini_projection(5)["safe_serialization_input_units_per_request"]
    for chunk in selection.chunks(words, settings):
        body = gemini_body(selection.prompt(chunk, settings, 3), settings)
        assert len(json.dumps(body, ensure_ascii=False).encode()) + 1024 <= bound


@pytest.mark.parametrize("kwargs", [{"fee": Decimal("1")}, {"fx": Decimal(0)}])
def test_invalid_financial_inputs_fail(kwargs):
    with pytest.raises(ValueError):
        audit.package(2000, Decimal("0.01"), **kwargs)
