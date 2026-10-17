"""Continuation workflow; original receipts are never reused or overwritten."""

import json
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import acceptance_once as driver
from fastapi.testclient import TestClient
from provision_acceptance import login, loopback_only
from sqlalchemy import text

from zoclip.ai.worker import deepgram_rate_label
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.credits.schemas import BudgetLimits
from zoclip.main import create_app
from zoclip.ops.acceptance_continuation import (
    ORIGINAL,
    ExecutionApproval,
    Permit,
    begin_workflow,
    committed_approval,
)
from zoclip.ops.local_bootstrap import isolated


def run_workflow(root: Path, permit: Permit, approval: ExecutionApproval) -> None:
    settings = Settings()  # type: ignore[call-arg]  # type: ignore[call-arg]
    if committed_approval(settings, root) != approval:
        raise ValueError("Execution approval changed")
    begin_workflow(settings, root, permit)
    out = permit.out
    # The entrypoint calls this ONLY after durable authorization consumption.
    ROOT = root
    PRIVATE = out
    EVIDENCE = ROOT / "var/live-ai-readiness/acceptance-admin"
    SAMPLE = ROOT.parent / "test-media/sample-live-test.mp4"
    RUN = {"operation_id": str(ORIGINAL), "authorization": approval.reason}
    state: dict[str, Any] = {"live_test": "BLOCKED", "error": None, "mp4_playable": False}

    def save(path: Path, value: Any, exclusive: bool = False) -> None:
        with path.open("x", encoding="utf-8") as f:
            json.dump(value, f, default=str, indent=2)
            f.flush()
            os.fsync(f.fileno())

    def request(
        client: TestClient,
        method: str,
        path: str,
        expected: int = 200,
        headers: dict | None = None,
        **kwargs: Any,
    ) -> Any:
        response = client.request(method, path, headers=headers, **kwargs)
        if response.status_code != expected:
            try:
                code = response.json().get("code", "http_failure")
            except Exception:
                code = "http_failure"
            raise ValueError(f"local_api_http_{response.status_code}:{code}")
        return response.json()

    def phase(name: str, owner: str, job: str) -> None:
        args = [
            sys.executable,
            str(ROOT / "scripts/acceptance_once.py"),
            "--phase",
            name,
            "--owner",
            owner,
            "--job",
            job,
        ]
        env = os.environ.copy()
        env["AI_ENABLED"] = "false"
        env["ZOCLIP_ACCEPTANCE_CONTINUATION"] = str(ORIGINAL)
        env.pop("ZOCLIP_ALLOW_PAID_ACCEPTANCE", None)
        if name == "ai":
            args.append("--allow-paid")
            env["ZOCLIP_ALLOW_PAID_ACCEPTANCE"] = "1"
        print("ENTER phase: " + name, flush=True)
        # Exactly one invocation. No subprocess timeout/restart/retry wrapper.
        result = subprocess.run(
            args, cwd=ROOT, env=env, capture_output=True, text=True, shell=False
        )
        save(
            PRIVATE / f"live-{name}-executor.json",
            {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            exclusive=True,
        )
        if result.returncode != 0:
            raise ValueError("acceptance_executor_stopped:" + name)
        print("PASS phase: " + name, flush=True)

    def main() -> None:
        settings = Settings()  # type: ignore[call-arg]
        isolated(settings)
        driver.models_ready(settings)
        if not all(
            getattr(settings, n).get_secret_value() for n in ("gemini_api_key", "deepgram_api_key")
        ):
            raise ValueError("provider_credentials_missing")
        if settings.deepgram_version != "2025-07-31.0":
            raise ValueError("wrong_version")
        if any(
            p.exists()
            for p in [driver.BINDING, *driver.BINDING.parent.glob("acceptance-*-entered.json")]
        ):
            raise ValueError("durable_acceptance_guard_already_consumed")
        source = SAMPLE.read_bytes()
        if sha256(source).hexdigest() != driver.SAMPLE_HASH:
            raise ValueError("sample_hash_mismatch")
        if (
            shutil.disk_usage(settings.media_root).free
            < settings.media_headroom_bytes + 3 * settings.media_max_bytes + 2 * 1024**3
        ):
            raise ValueError("insufficient_media_disk")
        resources = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$o=Get-CimInstance Win32_OperatingSystem; "
                "$w=@(Get-CimInstance Win32_Process | Where-Object {"
                "$_.CommandLine -match '(rq\\s+worker|zoclip\\..*worker|"
                "zoclip\\..*scheduler)'}); @{ram_kib=$o.FreePhysicalMemory;"
                "commit_kib=$o.FreeVirtualMemory;workers=$w.Count}|ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        resource = json.loads(resources.stdout)
        if resource["ram_kib"] < 524288 or resource["commit_kib"] < 524288 or resource["workers"]:
            raise ValueError("resource_or_background_worker_gate")
        customer = json.loads(
            (ROOT / "var/live-ai-readiness/acceptance-account/account.json").read_text()
        )
        admin = json.loads((EVIDENCE / "account.json").read_text())
        owner = customer["user_id"]
        state["owner"] = owner
        engine = build_engine(settings.database_url.get_secret_value())
        with engine.connect() as c:
            c.execute(text("SET TRANSACTION READ ONLY"))
            for table in ("jobs", "ai_requests", "spend_attempts", "provider_usage"):
                if c.scalar(text(f"SELECT count(*) FROM {table}")):
                    raise ValueError("existing_work_or_expense")
            if c.scalar(text("SELECT version_num FROM alembic_version")) != "7b37ea061d28":
                raise ValueError("migration_mismatch")
            if list(
                c.execute(
                    text("SELECT available,reserved FROM wallets WHERE user_id=:u"), {"u": owner}
                ).one()
            ) != [1, 0]:
                raise ValueError("one_credit_allowance_gate")
            policy = c.execute(
                text(
                    "SELECT p.limits,s.breaker FROM system_limits s JOIN cost_policy_versions p "
                    "ON p.id=s.policy_id"
                )
            ).one()
            if not policy.breaker:
                raise ValueError("breaker_initial_state_not_safe")
            limits = BudgetLimits.model_validate(policy.limits)
            expected = json.loads((EVIDENCE / "financial-receipt-2026-10-14.json").read_text())[
                "limits"
            ]
            if policy.limits != expected:
                raise ValueError("policy_changed")
            rates = {
                r.component: r
                for r in c.execute(
                    text("SELECT component,model,unit_usd,max_units FROM cost_rate_versions")
                )
            }
            if len(rates) != 5 or rates["deepgram"].model != deepgram_rate_label(settings):
                raise ValueError("model_rate_binding_gate")
            if sum(r.unit_usd * r.max_units for r in rates.values()) != Decimal("0.022572"):
                raise ValueError("rate_envelope_gate")
            if any(
                getattr(limits, n) != Decimal("0.05")
                for n in (
                    "per_job_usd",
                    "user_daily_usd",
                    "user_monthly_usd",
                    "global_daily_usd",
                    "global_monthly_usd",
                )
            ):
                raise ValueError("budget_gate")
        print("PASS exact configuration/hash/credit/policy/credential/guard preflight", flush=True)
        opened = False
        ah = ch = None
        attestation = json.loads(driver.ATTESTATION.read_text())
        with (
            loopback_only(),
            TestClient(create_app(settings), base_url="https://localhost") as ac,
            TestClient(create_app(settings), base_url="https://localhost") as cc,
        ):
            if not ac.app.state.redis.ping():  # type: ignore[attr-defined]
                raise ValueError("redis_unavailable")
            try:
                ah = login(ac, admin, settings.public_app_url)
                ch = login(cc, customer, settings.public_app_url)
                opened = True  # A response failure must still trigger audited closure.
                request(
                    ac,
                    "POST",
                    "/api/v1/admin/limits/versions",
                    headers={**ah, "Idempotency-Key": "acceptance-v1-policy-open"},
                    json={
                        "limits": policy.limits,
                        "breaker": False,
                        "reason": "Approved isolated one-shot acceptance; "
                        "preflight reconciled; open breaker",
                    },
                )
                opened = True
                attestation.update(
                    live_processing_approved=True,
                    live_operation_id=str(ORIGINAL),
                    continuation_authorization_id=str(approval.authorization_id),
                    live_approved_at=utcnow().isoformat(),
                    live_authorization=RUN["authorization"],
                )
                save(PRIVATE / "attestation-approved.json", attestation)
                save(PRIVATE / "live-authorization.json", RUN, exclusive=True)
                print(
                    "PASS audited spending policy opened; strict live approval recorded; "
                    "persisted AI false",
                    flush=True,
                )
                upload = request(
                    cc,
                    "POST",
                    "/api/v1/uploads",
                    201,
                    headers={**ch, "Idempotency-Key": "acceptance-live-upload"},
                    json={
                        "size_bytes": len(source),
                        "sha256": driver.SAMPLE_HASH,
                        "rights_attested": True,
                    },
                )
                state["video_id"] = upload["video_id"]
                for number, offset in enumerate(range(0, len(source), upload["part_bytes"])):
                    part = source[offset : offset + upload["part_bytes"]]
                    request(
                        cc,
                        "PUT",
                        f"/api/v1/uploads/{upload['id']}/parts/{number}",
                        headers={
                            **ch,
                            "Content-Type": "application/octet-stream",
                            "X-Content-SHA256": sha256(part).hexdigest(),
                        },
                        content=part,
                    )
                validate = request(
                    cc,
                    "POST",
                    f"/api/v1/uploads/{upload['id']}/complete",
                    202,
                    headers={**ch, "Idempotency-Key": "acceptance-live-complete"},
                )
                phase("validate", owner, validate["id"])
                quote = request(
                    cc,
                    "POST",
                    "/api/v1/jobs/quote",
                    headers={**ch, "Idempotency-Key": "acceptance-live-quote"},
                    json={
                        "source_seconds": 27,
                        "output_count": 1,
                        "edit_count": 0,
                        "captions": True,
                        "reframe": True,
                    },
                )
                if quote["credits"] != 1:
                    raise ValueError("quote_not_one_credit")
                job = request(
                    cc,
                    "POST",
                    f"/api/v1/videos/{upload['video_id']}/generate",
                    202,
                    headers={**ch, "Idempotency-Key": "acceptance-live-generate"},
                    json={"quote_id": quote["id"]},
                )
                state["job_id"] = job["id"]
                save(PRIVATE / "live-owned-ids.json", state, exclusive=True)
                phase("bind", owner, job["id"])
                state["live_test"] = "FAIL"
                phase("ai", owner, job["id"])
                transcript = request(cc, "GET", f"/api/v1/videos/{upload['video_id']}/transcript")
                suggestions = request(cc, "GET", f"/api/v1/videos/{upload['video_id']}/suggestions")
                if not transcript["data"]["words"] or not suggestions["items"]:
                    raise ValueError("empty_transcript_or_suggestions")
                save(
                    PRIVATE / "live-transcript-and-suggestions.json",
                    {"transcript": transcript, "suggestions": suggestions},
                    exclusive=True,
                )
                clip = request(
                    cc,
                    "POST",
                    "/api/v1/clips",
                    201,
                    headers=ch,
                    json={"suggestion_id": suggestions["items"][0]["id"]},
                )
                prefs = {**clip["preferences"], "preset": "classic", "frame": "center"}
                clip = request(
                    cc,
                    "PATCH",
                    f"/api/v1/clips/{clip['id']}",
                    headers={**ch, "If-Match": f'"{clip["revision"]}"'},
                    json=prefs,
                )
                state["clip_id"] = clip["id"]
                state["clip_preferences"] = prefs
                request(
                    cc,
                    "POST",
                    f"/api/v1/jobs/{job['id']}/renders",
                    202,
                    headers={**ch, "Idempotency-Key": "acceptance-live-render"},
                    json={"clip_ids": [clip["id"]]},
                )
                phase("render", owner, job["id"])
                download = cc.get(
                    f"/api/v1/clips/{clip['id']}/download", params={"revision": clip["revision"]}
                )
                if (
                    download.status_code != 200
                    or download.headers.get("content-type") != "video/mp4"
                ):
                    raise ValueError("private_download_failed")
                target = PRIVATE / "live-private-download.mp4"
                with target.open("xb") as f:
                    f.write(download.content)
                    f.flush()
                    os.fsync(f.fileno())
                probe = subprocess.run(
                    [
                        settings.ffprobe_binary,
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=25,
                )
                details = json.loads(probe.stdout)
                streams = details["streams"]
                assert {r["codec_type"] for r in streams} == {"audio", "video"}
                assert (
                    abs(
                        float(details["format"]["duration"])
                        - (prefs["end_ms"] - prefs["start_ms"]) / 1000
                    )
                    <= 0.1
                )
                decode = subprocess.run(
                    [
                        settings.ffmpeg_binary,
                        "-v",
                        "error",
                        "-xerror",
                        "-nostdin",
                        "-threads",
                        "2",
                        "-i",
                        str(target),
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if decode.returncode != 0:
                    raise ValueError("full_mp4_decode_failed")
                state.update(
                    mp4_playable=True,
                    output_path=str(target),
                    output_sha256=sha256(download.content).hexdigest(),
                    mp4_probe=details,
                    live_test="PASS",
                )
            finally:
                # Always revoke the one-process opt-in/attestation and block spending.
                os.environ.pop("ZOCLIP_ALLOW_PAID_ACCEPTANCE", None)
                attestation.update(
                    live_processing_approved=False, live_finished_at=utcnow().isoformat()
                )
                try:
                    save(PRIVATE / "stopped.json", {"stopped_at": utcnow().isoformat()})
                finally:
                    if opened and ah:
                        request(
                            ac,
                            "POST",
                            "/api/v1/admin/limits/versions",
                            headers={**ah, "Idempotency-Key": "acceptance-v1-policy-stop"},
                            json={
                                "limits": policy.limits,
                                "breaker": True,
                                "reason": "Close isolated acceptance after completion or stop; "
                                "preserve spend evidence",
                            },
                        )
                        print(
                            "PASS audited stop policy; spending blocked; AI remains disabled",
                            flush=True,
                        )
                    for client, headers in ((cc, ch), (ac, ah)):
                        if headers:
                            request(client, "POST", "/api/v1/auth/logout", headers=headers)
        engine.dispose()

    def report() -> None:
        settings = Settings()  # type: ignore[call-arg]
        engine = build_engine(settings.database_url.get_secret_value())
        try:
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                state["ai_disabled"] = not settings.ai_enabled
                state["spending_blocked"] = connection.scalar(
                    text("SELECT breaker FROM system_limits")
                )
                state["request_states"] = [
                    list(row)
                    for row in connection.execute(
                        text("SELECT provider,state FROM ai_requests ORDER BY created_at")
                    )
                ]
                state["wallets"] = [
                    list(row)
                    for row in connection.execute(text("SELECT available,reserved FROM wallets"))
                ]
        finally:
            engine.dispose()
        save(PRIVATE / "result.json", state)

    try:
        main()
    except BaseException as error:
        # Preserve failure evidence without logging credentials/provider payloads.
        state["error"] = type(error).__name__
        raise
    finally:
        if not (PRIVATE / "stopped.json").exists():
            save(PRIVATE / "stopped.json", {"stopped_at": utcnow().isoformat()})
        report()
