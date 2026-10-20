"""Focused Gemini 3.1/public-metadata contracts; mock transports only."""

import importlib.util
import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from zoclip.ai.providers import HTTPProviders, gemini_body
from zoclip.ai.schemas import Moments
from zoclip.ai.worker import usage
from zoclip.core.config import Settings
from zoclip.ops.local_bootstrap import financial_payloads, verified_batch_model


def module(name):
    spec = importlib.util.spec_from_file_location(name, f"scripts/{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def config():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://offline/offline",
        gemini_model="gemini-3.1-flash-lite",
        gemini_api_key="offline-fictional",
        deepgram_model="nova-3",
        deepgram_version="2025-07-31.0",
        deepgram_language="en",
        ai_max_chunks=1,
        ai_max_candidates=1,
        ai_chunk_bytes=16000,
        ai_max_output_tokens=2048,
        ai_enabled=False,
    )


def test_gemini_31_body_transport_and_thinking_usage():
    settings = config()
    body = gemini_body("Offline transcript", settings)
    generation = body["generationConfig"]
    assert generation["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert "temperature" not in generation and "thinkingBudget" not in generation["thinkingConfig"]
    assert generation["candidateCount"] == 1 and generation["maxOutputTokens"] == 2048
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"] == Moments.model_json_schema()
    seen = []

    def reply(request):
        seen.append(request)
        assert request.url.path == "/v1beta/models/gemini-3.1-flash-lite:generateContent"
        assert request.headers["x-goog-api-key"] == "offline-fictional"
        assert json.loads(request.read()) == body
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": '{"moments":[]}'},
                                {"text": "ignored thought", "thought": True},
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 10,
                    "totalTokenCount": 150,
                },
            },
        )

    result = HTTPProviders(settings, transport=httpx.MockTransport(reply)).analyze(body)
    assert len(seen) == 1 and usage(result, "gemini") == [120, 30]
    parts = result["body"]["candidates"][0]["content"]["parts"]
    assert Moments.model_validate_json("".join(p["text"] for p in parts if not p.get("thought")))
    legacy = gemini_body(
        "legacy", settings.model_copy(update={"gemini_model": "gemini-2.5-flash-lite"})
    )
    assert legacy["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


@pytest.mark.parametrize(
    "field,value",
    [
        ("gemini_model", "gemini-2.5-flash-lite"),
        ("gemini_model", "gemini-3.5-flash-lite"),
        ("deepgram_version", ""),
        ("deepgram_version", "latest"),
        ("deepgram_version", "beta"),
        ("ai_max_chunks", 2),
    ],
)
def test_amended_driver_guards(field, value):
    driver = module("acceptance_once")
    driver.models_ready(config())
    with pytest.raises(ValueError):
        driver.models_ready(config().model_copy(update={field: value}))


def row(version="2025-07-31.0", **updates):
    return {
        "name": "general",
        "canonical_name": "nova-3-general",
        "architecture": "nova-3",
        "version": version,
        "uuid": str(uuid4()),
        "languages": ["en", "en-US"],
        "batch": True,
        "streaming": False,
        "multilingual": False,
        **updates,
    }


def test_verified_metadata_selects_fixed_monolingual_general_pin():
    selected = row()
    record = {
        "status": 200,
        "body": {
            "stt": [
                row("2024-12-20.0"),
                selected,
                row("2026-01-27.9107", multilingual=True),
                row(batch=False, streaming=True),
                row("2026-09-30.28661", name="medical", canonical_name="nova-3-medical"),
            ]
        },
    }
    assert verified_batch_model(record) == selected
    evidence = {
        "rate_basis": "approved_public_standard_prices_2026-10-14",
        "nova3_english_batch_confirmed": True,
        "source": "offline metadata fixture",
        "verified_at": "2026-10-14",
        "deepgram_version": selected["version"],
    }
    rates, policy = financial_payloads(config(), evidence)
    total = sum((Decimal(r["unit_usd"]) * r["max_units"] for r in rates), Decimal(0))
    assert total == Decimal("0.022572") and policy["breaker"] is True


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row(batch=False)],
        [row(multilingual=True)],
        [row("latest")],
        [row("2025-07-31.0"), row("2025-07-31.0")],
    ],
)
def test_metadata_missing_moving_or_ambiguous_refused(rows):
    with pytest.raises(ValueError):
        verified_batch_model({"status": 200, "body": {"stt": rows}})


@pytest.mark.parametrize("outcome", [200, 302, 429, "timeout"])
def test_metadata_get_exactly_once_no_auth_retry_or_restart(tmp_path, outcome):
    discovery = module("discover_deepgram_once")
    seen = []

    def reply(request):
        seen.append(request)
        assert request.method == "GET" and str(request.url) == discovery.URL
        assert "authorization" not in request.headers and request.read() == b""
        if outcome == "timeout":
            raise httpx.ReadTimeout("mock timeout", request=request)
        return httpx.Response(
            outcome, json={"stt": []}, headers={"Location": "https://other.invalid"}
        )

    transport = httpx.MockTransport(reply)
    if outcome == "timeout":
        with pytest.raises(httpx.ReadTimeout):
            discovery.discover(tmp_path, transport)
    else:
        assert discovery.discover(tmp_path, transport)["status"] == outcome
    with pytest.raises(FileExistsError):
        discovery.discover(tmp_path, transport)
    assert len(seen) == 1
