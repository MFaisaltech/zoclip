import json

import httpx
import pytest

from zoclip.core.config import Settings
from zoclip.ops.provider_metadata import verify


def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://offline/offline",
        gemini_model="gemini-3.1-flash-lite",
        deepgram_api_key="offline-deepgram-key-not-real-000",
        gemini_api_key="offline-gemini-key-not-real-0000",
    )


def test_metadata_only_and_secret_redaction(tmp_path):
    s = settings()
    calls = []

    def respond(request):
        assert request.method == "GET" and request.content == b""
        calls.append(request.url.path)
        if request.url.host == "api.deepgram.com":
            assert (
                request.headers["authorization"] == "Token " + s.deepgram_api_key.get_secret_value()
            )
            return httpx.Response(200, json={"secret": s.deepgram_api_key.get_secret_value()})
        return httpx.Response(
            200,
            json={
                "name": "models/gemini-3.1-flash-lite",
                "inputTokenLimit": 1000000,
                "outputTokenLimit": 65536,
                "supportedGenerationMethods": ["generateContent"],
            },
        )

    result = verify(s, tmp_path, httpx.MockTransport(respond))
    assert len(calls) == 2 and all(v["credential_accepted"] for v in result["providers"].values())
    assert result["inference_requests"] == 0
    for file in tmp_path.iterdir():
        assert s.deepgram_api_key.get_secret_value() not in file.read_text()
        assert s.gemini_api_key.get_secret_value() not in file.read_text()
    with pytest.raises(FileExistsError):
        verify(s, tmp_path, httpx.MockTransport(lambda r: pytest.fail("No replay")))


@pytest.mark.parametrize("failure", ["401", "429", "redirect", "timeout", "huge", "json"])
def test_metadata_errors_stop_without_retry(tmp_path, failure):
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("injected")
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.invalid"})
        if failure == "huge":
            return httpx.Response(200, content=b"x" * (256 * 1024 + 1))
        if failure == "json":
            return httpx.Response(200, content=b"invalid")
        return httpx.Response(int(failure), json={})

    result = verify(settings(), tmp_path, httpx.MockTransport(respond))
    assert len(calls) == 1
    assert result["providers"]["deepgram"]["credential_accepted"] is False
    assert not (tmp_path / "gemini-metadata-entered.json").exists()
    assert json.loads((tmp_path / "metadata-summary.json").read_text())["inference_requests"] == 0
