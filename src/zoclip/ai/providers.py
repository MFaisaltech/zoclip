"""Official HTTPS REST adapters, no implicit retries or configurable destinations."""

import json
import ssl
import time
from pathlib import Path
from typing import Protocol

import httpx

from zoclip.ai.schemas import Moments
from zoclip.core.config import Settings

MAX_RESPONSE = 8 * 1024**2


class ProviderFailure(Exception):
    """Unknown remote outcome: NEVER permission to retry a paid request."""


class Providers(Protocol):
    def transcribe(self, path: Path) -> dict: ...
    def analyze(self, body: dict) -> dict: ...


def gemini_body(prompt: str, settings: Settings) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "candidateCount": 1,
            "maxOutputTokens": settings.ai_max_output_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
            "responseJsonSchema": Moments.model_json_schema(),
        },
    }


class HTTPProviders:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings, self.transport = settings, transport

    def request(
        self, url: str, headers: dict, *, limit: int = MAX_RESPONSE, **kwargs: object
    ) -> dict:
        deadline = time.monotonic() + self.settings.ai_provider_timeout_seconds
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.settings.ai_provider_timeout_seconds, connect=10),
                trust_env=False,
                verify=ssl.create_default_context(),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                with client.stream("POST", url, headers=headers, **kwargs) as response:  # type: ignore[arg-type]
                    data = bytearray()
                    for chunk in response.iter_bytes(65536):
                        if time.monotonic() > deadline or len(data) + len(chunk) > limit:
                            raise ProviderFailure("provider_response_limit")
                        data.extend(chunk)
                    try:
                        body = json.loads(data)
                    except (ValueError, UnicodeError):
                        body = None
                    return {"status": response.status_code, "body": body}
        except httpx.HTTPError as exc:
            raise ProviderFailure("provider_outcome_unknown") from exc

    def transcribe(self, path: Path) -> dict:
        s = self.settings
        with path.open("rb") as audio:
            return self.request(
                "https://api.deepgram.com/v1/listen",
                {
                    "Authorization": "Token " + s.deepgram_api_key.get_secret_value(),
                    "Content-Type": "audio/wav",
                },
                params={
                    "model": s.deepgram_model,
                    "version": s.deepgram_version,
                    "language": s.deepgram_language,
                    "punctuate": "true",
                    "diarize": str(s.deepgram_diarize).lower(),
                    "utterances": str(s.deepgram_utterances).lower(),
                    "mip_opt_out": str(s.deepgram_mip_opt_out).lower(),
                },
                content=iter(lambda: audio.read(65536), b""),
            )

    def analyze(self, body: dict) -> dict:
        return self.request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + self.settings.gemini_model
            + ":generateContent",
            {"x-goog-api-key": self.settings.gemini_api_key.get_secret_value()},
            limit=256 * 1024,
            json=body,
        )
