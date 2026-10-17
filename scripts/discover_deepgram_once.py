"""Exactly one approved public metadata GET. No keys, audio, redirects or retries."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "var/live-ai-readiness/acceptance-admin"
URL = "https://api.deepgram.com/v1/models"


def exclusive(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def discover(directory: Path, transport: httpx.BaseTransport | None = None) -> dict:
    # A consumed marker is never removed, even on DNS/TLS/timeout/HTTP failure.
    exclusive(
        directory / "deepgram-models-entered.json",
        {
            "method": "GET",
            "url": URL,
            "authenticated": False,
            "entered_at": datetime.now(UTC).isoformat(),
            "max_requests": 1,
        },
    )
    with httpx.Client(
        transport=transport or httpx.HTTPTransport(retries=0),
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(30, connect=10),
    ) as client:
        with client.stream("GET", URL, headers={"Accept": "application/json"}) as response:
            raw = bytearray()
            for chunk in response.iter_bytes(65536):
                if len(raw) + len(chunk) > 2 * 1024**2:
                    raise ValueError("Metadata response exceeds bound; no repeat permitted")
                raw.extend(chunk)
            record = {
                "status": response.status_code,
                "body": json.loads(raw),
                "received_at": datetime.now(UTC).isoformat(),
            }
    exclusive(directory / "deepgram-models-response.json", record)
    return record


if __name__ == "__main__":
    try:
        record = discover(PRIVATE)
        print(
            json.dumps(
                {
                    "status": record["status"],
                    "nova3_english_batch_entries": [
                        row
                        for row in record["body"].get("stt", [])
                        if row.get("batch") is True
                        and "en" in row.get("languages", [])
                        and (
                            "nova-3" in row.get("canonical_name", "")
                            or row.get("architecture") == "nova3"
                        )
                    ],
                }
            )
        )
    except Exception as error:
        print("STOP: " + type(error).__name__ + "; metadata permission consumed; do not retry")
        raise SystemExit(1) from None
