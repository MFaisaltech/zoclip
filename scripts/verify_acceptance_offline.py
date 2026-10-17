"""Repeatable offline guard gate: fresh preserved mock schemas; no reset/drop/live IO."""

import argparse
import json
import os
import socket
import threading
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

from zoclip.core.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation-only", action="store_true")
    parser.add_argument("--maxfail", type=int, default=0)
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    url = make_url(settings.database_url.get_secret_value())
    if settings.ai_enabled or (url.host, url.port, url.database) != (
        "127.0.0.1",
        55439,
        "zoclip_live_readiness",
    ):
        raise ValueError("Disabled isolated readiness configuration required")
    root = Path(__file__).resolve().parents[1]
    state_dir = Path((root / "var/live-ai-readiness/current-services.txt").read_text().strip())
    if not state_dir.resolve().is_relative_to(root / "var/live-ai-readiness"):
        raise ValueError("Unexpected service metadata location")
    state = json.loads((state_dir / "state.json").read_text())
    database = state["mock_database_name"]
    if not database.startswith("zoclip_mock_") or not database.endswith("_test"):
        raise ValueError("Separate saved mock database required")
    test_url = url.set(database=database).render_as_string(hide_password=False)
    os.environ.update(
        {
            "ZOCLIP_ACCEPTANCE_TEST_DATABASE_URL": test_url,
            "DATABASE_URL": test_url,
            "GEMINI_API_KEY": "",
            "DEEPGRAM_API_KEY": "",
            "AI_ENABLED": "false",
            "FFMPEG_BINARY": settings.ffmpeg_binary,
            "FFPROBE_BINARY": settings.ffprobe_binary,
        }
    )
    for name in ("TEST_DATABASE_URL", "TEST_REDIS_URL", "ZOCLIP_ALLOW_PAID_ACCEPTANCE"):
        os.environ.pop(name, None)
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo
    original_pair = socket.socketpair
    internal = threading.local()

    def local_pair(*args, **kwargs):  # type: ignore[no-untyped-def]
        internal.socketpair = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            internal.socketpair = False

    def connect(sock, address):  # type: ignore[no-untyped-def]
        if (
            isinstance(address, tuple)
            and address[0] in {"127.0.0.1", "::1"}
            and (address[1] == 55439 or getattr(internal, "socketpair", False))
        ):
            return original_connect(sock, address)
        raise RuntimeError("External network blocked by offline guard gate")

    def dns(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host in {"127.0.0.1", "localhost", "::1"}:
            return original_dns(host, *args, **kwargs)
        raise RuntimeError("External DNS blocked by offline guard gate")

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.getaddrinfo = dns  # type: ignore[assignment]
    socket.socketpair = local_pair
    import pytest

    evidence = root / "var" / ("acceptance-guard-tests-" + uuid4().hex)
    evidence.mkdir()
    nodes = (
        [
            "tests/test_acceptance_once.py",
            "tests/test_local_bootstrap.py",
            "tests/test_provider_amendment.py",
            "tests/test_acceptance_continuation.py",
        ]
        + [
            "tests/test_ai.py::" + name
            for name in (
                "test_alignment_overlap_clamping_and_ranking",
                "test_unicode_chunking_bounded_and_absolute_timestamps",
                "test_official_http_adapter_bounded_auth_no_redirects",
                "test_usage_includes_thinking_overrun_and_breaker",
                "test_ai_configuration_fail_closed",
                "test_adapter_response_size_timeout_and_malformed_data",
            )
        ]
        + [
            "tests/test_config.py::test_reject_unsafe_config",
            "tests/test_config.py::test_openapi_is_valid_and_matches_export",
        ]
    )
    if args.continuation_only:
        nodes = ["tests/test_acceptance_continuation.py"]
    print("Offline providers only; fresh preserved mock schemas, no reset/drop.")
    try:
        return int(
            pytest.main(
                nodes
                + [
                    "-q",
                    "--tb=short",
                    f"--maxfail={args.maxfail}",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(evidence / "tmp"),
                    "--junitxml",
                    str(evidence / "results.xml"),
                ]
            )
        )
    finally:
        socket.socket.connect, socket.getaddrinfo = original_connect, original_dns  # type: ignore[method-assign]
        socket.socketpair = original_pair


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("STOP: " + type(exc).__name__)
        raise SystemExit(1) from None
