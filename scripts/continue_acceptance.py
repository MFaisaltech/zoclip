"""Explicit-only original-operation continuation; no automatic approval or rearm."""

import argparse
import json
import logging
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import acceptance_once as driver
from redis import Redis
from sqlalchemy.orm import sessionmaker

from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.ops.acceptance_continuation import (
    ExecutionApproval,
    digest,
    execute_approved,
    historical_evidence,
    implementation_digest,
)
from zoclip.ops.local_bootstrap import isolated

ROOT = Path(__file__).resolve().parents[1]


def resources(settings: Settings) -> None:
    """Original 512 MiB RAM/commit, no-background-worker and disk gates."""
    if shutil.disk_usage(settings.media_root).free < (
        settings.media_headroom_bytes + 3 * settings.media_max_bytes + 2 * 1024**3
    ):
        raise ValueError("insufficient_media_disk")
    script = (
        "$ErrorActionPreference='Stop'; $o=Get-CimInstance Win32_OperatingSystem; "
        "$w=@(Get-CimInstance Win32_Process | Where-Object {"
        "$_.CommandLine -match '(rq\\s+worker|zoclip\\..*worker|zoclip\\..*scheduler)'}); "
        "@{ram_kib=$o.FreePhysicalMemory;commit_kib=$o.FreeVirtualMemory;"
        "workers=$w.Count}|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    value = json.loads(result.stdout)
    if value["ram_kib"] < 524288 or value["commit_kib"] < 524288 or value["workers"]:
        raise ValueError("resource_or_background_worker_gate")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--approval", type=Path)
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    isolated(settings)
    driver.isolated(settings)
    driver.models_ready(settings)
    if any(
        os.environ.get(k)
        for k in (
            "TEST_DATABASE_URL",
            "ZOCLIP_PROVIDER_SIMULATOR",
            "ZOCLIP_ALLOW_PAID_ACCEPTANCE",
            "ZOCLIP_ACCEPTANCE_CONTINUATION",
        )
    ):
        raise ValueError("Unexpected test/paid overrides")
    if not args.execute:
        if args.approval or args.allow_paid:
            parser.error("Approval consumption requires --execute --allow-paid")
        print(
            json.dumps(
                {
                    "evidence_sha256": digest(historical_evidence(ROOT)),
                    "implementation_sha256": implementation_digest(ROOT),
                    "consumed": False,
                }
            )
        )
        return
    if not args.allow_paid or not args.approval:
        parser.error("Execution requires --allow-paid and a fresh --approval file")
    private = ROOT / "var/live-ai-readiness/acceptance-admin"
    if not args.approval.resolve().is_relative_to(private.resolve()):
        raise ValueError("Approval must remain in the existing private directory")
    approval = ExecutionApproval.model_validate_json(args.approval.read_text())
    approval.check(utcnow())
    if not all(
        getattr(settings, n).get_secret_value() for n in ("gemini_api_key", "deepgram_api_key")
    ):
        raise ValueError("Provider credentials absent")
    if settings.deepgram_version != "2025-07-31.0":
        raise ValueError("Pinned version changed")
    if sha256((ROOT.parent / "test-media/sample-live-test.mp4").read_bytes()).hexdigest() != (
        driver.SAMPLE_HASH
    ):
        raise ValueError("Sample changed")
    with Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=3) as redis:
        if (
            not redis.ping()
            or redis.scard("rq:workers")
            or any(redis.llen(k) for k in redis.scan_iter(match="rq:queue:*"))
        ):
            raise ValueError("Redis unavailable or competing work exists")
    engine = build_engine(settings.database_url.get_secret_value())
    from acceptance_continuation_workflow import run_workflow

    try:
        execute_approved(
            sessionmaker(engine, expire_on_commit=False),
            ROOT,
            approval,
            lambda: resources(settings),
            lambda permit: run_workflow(ROOT, permit, approval),
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        main()
    except Exception as exc:
        print("STOP: " + type(exc).__name__)
        raise SystemExit(1) from None
