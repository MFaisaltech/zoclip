"""Read-only credential/model checks. This module cannot submit paid inference."""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from zoclip.core.config import Settings

TARGETS = {
    "deepgram": "https://api.deepgram.com/v1/auth/token",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite",
}


def exclusive(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def verify(
    settings: Settings, directory: Path, transport: httpx.BaseTransport | None = None
) -> dict:
    if settings.ai_enabled or settings.gemini_model != "gemini-3.1-flash-lite":
        raise ValueError("Disabled reviewed model configuration required")
    keys = {
        "deepgram": settings.deepgram_api_key.get_secret_value(),
        "gemini": settings.gemini_api_key.get_secret_value(),
    }
    if any(len(value) < 20 for value in keys.values()):
        raise ValueError("Private provider keys required")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    result: dict = {
        "checked_at": datetime.now(UTC).isoformat(),
        "inference_requests": 0,
        "account_specific_rates_verified": False,
        "providers": {},
    }
    for provider, url in TARGETS.items():
        exclusive(
            directory / (provider + "-metadata-entered.json"),
            {
                "method": "GET",
                "url": url,
                "body": None,
                "credential_sha256": hashlib.sha256(keys[provider].encode()).hexdigest(),
                "entered_at": datetime.now(UTC).isoformat(),
                "max_requests": 1,
            },
        )
        record: dict = {"method": "GET", "credential_accepted": False, "inference_requests": 0}
        try:
            headers = (
                {"Authorization": "Token " + keys[provider]}
                if provider == "deepgram"
                else {"x-goog-api-key": keys[provider]}
            )
            deadline = time.monotonic() + 30
            with httpx.Client(
                transport=transport or httpx.HTTPTransport(retries=0),
                timeout=httpx.Timeout(15, connect=10),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", url, headers=headers) as response:
                    raw = bytearray()
                    for chunk in response.iter_bytes(65536):
                        if len(raw) + len(chunk) > 256 * 1024 or time.monotonic() > deadline:
                            raise ValueError("Metadata response limit")
                        raw.extend(chunk)
                    record["status"] = response.status_code
                    if response.status_code != 200:
                        raise ValueError("Metadata authentication refused")
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError("Metadata response structure")
                    if provider == "gemini":
                        if (
                            body.get("name") != "models/gemini-3.1-flash-lite"
                            or "generateContent" not in body.get("supportedGenerationMethods", [])
                            or type(body.get("inputTokenLimit")) is not int
                            or type(body.get("outputTokenLimit")) is not int
                            or body["inputTokenLimit"] < 36000
                            or body["outputTokenLimit"] < 2048
                        ):
                            raise ValueError("Reviewed model unavailable")
                        record.update(
                            model=body["name"],
                            input_limit=body["inputTokenLimit"],
                            output_limit=body["outputTokenLimit"],
                            generate_content_metadata_available=True,
                        )
                    else:
                        # No response body, key IDs, project IDs or token material is persisted.
                        if not body:
                            raise ValueError("Empty key verification response")
                        record["response_fields"] = sorted(body)
                        scopes = body.get("scopes", [])
                        record["transcription_scope_reported"] = (
                            isinstance(scopes, list) and "usage:write" in scopes
                        )
                    record["credential_accepted"] = True
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            record["failure_type"] = type(exc).__name__
        exclusive(directory / (provider + "-metadata-result.json"), record)
        result["providers"][provider] = record
        if not record["credential_accepted"]:
            break  # No retry, permission increase or inference probe.
    exclusive(directory / "metadata-summary.json", result)
    return result
