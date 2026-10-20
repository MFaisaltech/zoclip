"""Isolated synthetic acceptance ONLY: disposable PG/Redis, never deployed DB.

The controller must supply an internal-only Docker network, disposable database
ending _test, a new work directory, no deployed secrets and explicit opt-in.
ASGI HTTP upload is measured; external network upload speed is not.
"""

import hashlib
import json
import logging
import os
import resource
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from zoclip.ai import audio
from zoclip.ai.models import AIRequest, Transcript
from zoclip.ai.providers import HTTPProviders, LocalWhisperProviders, ProviderFailure
from zoclip.auth.models import AuthSession, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits import service as money
from zoclip.credits.models import Plan, Wallet
from zoclip.credits.schemas import (
    BudgetLimits,
    ConsumptionRules,
    PlanVersionInput,
    PolicyInput,
    RateInput,
)
from zoclip.main import create_app
from zoclip.media import service, worker
from zoclip.media.models import Job, JobEvent, StorageObject
from zoclip.media.storage import LocalStorage
from zoclip.rendering import engine
from zoclip.rendering.models import RenderOutput
from zoclip.rendering.schemas import Preferences


def run(base: Path) -> None:
    if os.environ.get("ZOCLIP_SYNTHETIC_ACCEPTANCE") != "1":
        raise RuntimeError("Explicit isolated synthetic opt-in required")
    if (
        make_url(os.environ["DATABASE_URL"]).host != "synthetic-db"
        or make_url(os.environ["DATABASE_URL"]).database != "synthetic_capacity_test"
    ):
        raise RuntimeError("Disposable synthetic database required")
    work = base / "work"
    resume = os.environ.get("ZOCLIP_SYNTHETIC_RESUME") == "1"
    work.mkdir(mode=0o700, exist_ok=resume)
    os.environ.update(
        APP_ENV="test",
        MEDIA_ROOT=str(work),
        AI_ENABLED="true",
        GEMINI_MODEL="gemini-3.1-flash-lite",
        GEMINI_API_KEY="synthetic-unused-not-a-key",
        TRANSCRIPTION_PROVIDER="whisper",
        PAYMENT_PROVIDER="disabled",
    )
    settings = Settings(_env_file=None, _secrets_dir=None, cookie_secure=False, auth_rate_limit=100)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(settings)
    factory = app.state.session_factory
    storage = LocalStorage(settings.media_root)
    reason = "Disposable synthetic benchmark, never real customer credit or cost"
    rules = ConsumptionRules(
        minimum_job_credits=60,
        credits_per_minute=5,
        credits_per_output=2,
        credits_per_edit=2,
        captions_credits=0,
        reframe_credits=0,
        max_source_seconds=7200,
        max_outputs=3,
        max_edits=1,
        max_concurrent_jobs=1,
        daily_credits=650,
        monthly_credits=3700,
    )
    if not resume:
        with factory() as db:
            admin = User(email="synthetic-admin@example.com", verified=True, role="admin")
            db.add(admin)
            db.flush()
            plan = db.scalar(select(Plan).where(Plan.slug == "creator"))
            price = money.configure_plan(
                db,
                plan.id,
                PlanVersionInput(
                    price_paisa=200000,
                    included_credits=3700,
                    valid_days=30,
                    approved=False,
                    rules=rules,
                    reason=reason,
                ),
                "synthetic-only",
                admin.id,
            )
            # Positive fictional rates exercise admission/accounting. Not financial evidence.
            rates = [
                money.configure_rate(
                    db,
                    RateInput(
                        component=c,
                        unit=u,
                        unit_usd=Decimal("0.0000000001"),
                        model=settings.gemini_model
                        if c.startswith("gemini")
                        else "synthetic-unused",
                        max_units=10**9,
                        reason=reason,
                    ),
                    "synthetic-rate",
                    admin.id,
                ).id
                for c, u in [
                    ("deepgram", "minute"),
                    ("gemini_input", "token"),
                    ("gemini_output", "token"),
                    ("render", "cpu_second"),
                    ("storage", "gb_day"),
                ]
            ]
            money.configure_policy(
                db,
                PolicyInput(
                    reason=reason,
                    limits=BudgetLimits(
                        per_job_usd=Decimal(10),
                        user_daily_usd=Decimal(100),
                        user_monthly_usd=Decimal(100),
                        global_daily_usd=Decimal(100),
                        global_monthly_usd=Decimal(100),
                        max_open_reservations=10,
                        rate_ids=rates,
                        input_tokens_per_second=1,
                        max_output_tokens=2048,
                        render_cpu_seconds_per_output=520,
                        storage_gb_days_per_output=2,
                        max_attempts_per_job=100,
                    ),
                ),
                "synthetic-policy",
                admin.id,
            )
            users = {}
            for minutes in (5, 30, 120):
                user = User(email=f"synthetic-{minutes}@example.com", verified=True)
                db.add(user)
                db.flush()
                money.grant_entitlement(db, user.id, price.id, "synthetic-grant", admin.id, reason)
                users[minutes] = user.id
            db.commit()
    else:
        with factory() as db:
            users = {
                m: db.scalar(select(User.id).where(User.email == f"synthetic-{m}@example.com"))
                for m in (5, 30, 120)
            }
            if not all(users.values()):
                raise RuntimeError("Cannot resume missing disposable benchmark users")

    phases = (
        [json.loads(line) for line in (base / "phases.jsonl").read_text().splitlines()]
        if resume
        else []
    )
    current = {"minutes": None}
    original_extract, original_transcribe, original_render = (
        audio.extract,
        LocalWhisperProviders.transcribe_chunk,
        engine.render,
    )
    pressure = {}
    pool = ThreadPoolExecutor(max_workers=1)
    pressure_future = None

    def measure(name, operation):
        started = time.monotonic()
        a = resource.getrusage(resource.RUSAGE_SELF)
        b = resource.getrusage(resource.RUSAGE_CHILDREN)
        row = {"minutes": current["minutes"], "stage": name}
        try:
            value = operation()
            row["result"] = "PASS"
            return value
        except Exception as exc:
            row.update(result="FAIL", error_code=getattr(exc, "code", type(exc).__name__))
            if isinstance(exc, ProviderFailure):
                row["adapter_failure"] = (
                    str(exc)
                    if str(exc)
                    in {
                        "whisper_transcription_failed",
                        "whisper_invalid_audio",
                        "whisper_model_unavailable",
                        "whisper_deadline_exceeded",
                    }
                    else "redacted"
                )
                cause = exc.__context__
                trace = cause.__traceback__ if cause else None
                while trace:
                    if (
                        trace.tb_frame.f_code.co_name in {"transcribe", "transcribe_chunk"}
                        and Path(trace.tb_frame.f_code.co_filename).name == "providers.py"
                    ):
                        row["adapter_failure_source_line"] = trace.tb_lineno
                    trace = trace.tb_next
            raise
        finally:
            c = resource.getrusage(resource.RUSAGE_SELF)
            d = resource.getrusage(resource.RUSAGE_CHILDREN)
            row.update(
                wall_seconds=time.monotonic() - started,
                cpu_seconds=c.ru_utime
                + c.ru_stime
                - a.ru_utime
                - a.ru_stime
                + d.ru_utime
                + d.ru_stime
                - b.ru_utime
                - b.ru_stime,
                process_peak_rss_kib=c.ru_maxrss,
                child_peak_rss_kib_cumulative=d.ru_maxrss,
            )
            phases.append(row)
            with (base / "phases.jsonl").open("a") as handle:
                handle.write(json.dumps(row) + "\n")

    def extract(*args, **kwargs):
        return measure("audio_extraction", lambda: original_extract(*args, **kwargs))

    def transcribe(self, path, start, stop, progress=lambda: None, **bounds):
        nonlocal pressure_future
        marker = base / "pressure-started"
        if current["minutes"] == 5 and not marker.exists():
            marker.touch(exist_ok=False)

            def pressure_render():
                try:
                    result = measure(
                        "concurrent_90s_render",
                        lambda: original_render(
                            base / "media/synthetic-5min.mp4",
                            base / "pressure-render.mp4",
                            Preferences(start_ms=0, end_ms=90000),
                            [{"word": "Synthetic", "start": 0, "end": 1}],
                            settings,
                            lambda: None,
                        ),
                    )
                    receipt = {"result": "PASS", "output_bytes": result["size_bytes"]}
                except Exception:
                    receipt = {"result": "FAIL", "output_bytes": 0}
                    raise
                finally:
                    (base / "pressure-result.json").write_text(json.dumps(receipt))
                return result

            pressure_future = pool.submit(pressure_render)
        result = measure(
            "local_whisper",
            lambda: original_transcribe(self, path, start, stop, progress, **bounds),
        )
        if pressure_future is not None:
            pressure_future.result(timeout=300)  # Finish before this RQ work horse exits.
        return result

    def mock_analyze(self, body):
        prompt = body["contents"][0]["parts"][0]["text"]
        segments = json.loads(prompt.split("\n", 1)[1])
        start = segments[0]["start"]
        end = min(segments[-1]["end"], start + 29)
        moments = (
            [
                {
                    "start_sec": start,
                    "end_sec": end,
                    "title": "Synthetic selection",
                    "hook": "Mock candidate",
                    "reason": "Infrastructure fixture only",
                    "score": 50,
                    "keywords": [],
                    "hashtags": [],
                }
            ]
            if end - start >= 15
            else []
        )
        encoded = json.dumps({"moments": moments})
        return {
            "status": 200,
            "body": {
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": encoded}]}}],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 100,
                    "thoughtsTokenCount": 0,
                    "totalTokenCount": 200,
                },
            },
        }

    def forbid(*args, **kwargs):
        raise RuntimeError("Paid provider dispatch forbidden in synthetic acceptance")

    original_popen = audio.subprocess.Popen

    class ObservedExtractor(original_popen):
        def __init__(self, args, **kwargs):
            self.started = time.monotonic()
            self.cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN)
            self.error_path = base / ("extract-error-" + uuid4().hex + ".log")
            self.error_handle = self.error_path.open("wb")
            kwargs["stderr"] = self.error_handle
            super().__init__(args, **kwargs)

        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                self.error_handle.close()
                child = resource.getrusage(resource.RUSAGE_CHILDREN)
                with self.error_path.open("rb") as handle:
                    handle.seek(max(0, self.error_path.stat().st_size - 3000))
                    stderr = handle.read().decode(errors="replace")
                row = {
                    "return_code": self.returncode,
                    "wall_seconds": time.monotonic() - self.started,
                    "child_cpu_seconds": child.ru_utime
                    + child.ru_stime
                    - self.cpu_start.ru_utime
                    - self.cpu_start.ru_stime,
                    "command": self.args,
                    "stderr": stderr,
                }
                with (base / "extraction-processes.jsonl").open("a") as handle:
                    handle.write(json.dumps(row) + "\n")

    def observe_audio(args, *positional, **kwargs):
        if isinstance(args, list) and "zoclip.ai.audio_runner" in args:
            return ObservedExtractor(args, **kwargs)
        return original_popen(args, *positional, **kwargs)

    audio.subprocess.Popen = observe_audio
    original_run_job = worker.run_job

    def measured_claim(*args, **kwargs):
        return measure("worker_claim", lambda: original_run_job(*args, **kwargs))

    worker.run_job = measured_claim
    audio.extract = extract
    LocalWhisperProviders.transcribe_chunk = transcribe
    LocalWhisperProviders.analyze = mock_analyze
    HTTPProviders.request = forbid
    engine.render = lambda *a, **k: measure("captioned_render", lambda: original_render(*a, **k))
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    manifest = json.loads((base / "media/manifest.json").read_text())
    results = []
    with TestClient(app, base_url="http://localhost:8000") as client:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        for source in manifest["files"]:
            minutes = source["minutes"]
            current["minutes"] = minutes
            if resume:
                with factory() as db:
                    prior = db.scalar(
                        select(Job).where(
                            Job.user_id == users[minutes],
                            Job.kind == "PROCESS",
                            Job.state.in_(["COMPLETED", "FAILED", "CANCELED"]),
                        )
                    )
                    if prior is not None:
                        wallet = db.scalar(select(Wallet).where(Wallet.user_id == users[minutes]))
                        outputs = list(
                            db.scalars(select(RenderOutput).where(RenderOutput.job_id == prior.id))
                        )
                        first = db.scalar(
                            select(func.min(JobEvent.created_at)).where(
                                JobEvent.job_id == prior.id, JobEvent.state == "RUNNING"
                            )
                        )
                        row = {
                            "minutes": minutes,
                            "state": prior.state,
                            "error": prior.error_code,
                            "accepted_to_terminal_seconds": sum(
                                p["wall_seconds"]
                                for p in phases
                                if p["minutes"] == minutes
                                and p["stage"]
                                in ["ASGI_HTTP_chunked_upload", "validation_RQ", "processing_RQ"]
                            ),
                            "wallet_available": wallet.available,
                            "wallet_reserved": wallet.reserved,
                            "quote_credits": prior.checkpoint.get("estimated_credits"),
                            "outputs": len(outputs),
                            "output_bytes": sum(
                                o.metadata_json.get("size_bytes", 0) for o in outputs
                            ),
                            "queue_wait_samples_seconds": [
                                (first - prior.created_at).total_seconds()
                            ]
                            if first
                            else [],
                            "queue_wait_scope": "SQL acceptance to first claim",
                            "recovered_without_reexecution": True,
                        }
                        results.append(row)
                        (base / f"result-{minutes}.json").write_text(json.dumps(row, indent=2))
                        continue
            raw, csrf = uuid4().hex, uuid4().hex
            with factory() as db:
                db.add(
                    AuthSession(
                        user_id=users[minutes],
                        token_hash=digest(raw),
                        csrf_hash=digest(csrf),
                        expires_at=utcnow() + timedelta(hours=2),
                    )
                )
                db.commit()
            client.cookies.set(COOKIE_NAME, raw)
            sequence = 0

            def post(path, data=None, csrf=csrf, minutes=minutes):
                nonlocal sequence
                sequence += 1
                response = client.post(
                    path,
                    json=data,
                    headers={
                        "Origin": settings.public_app_url,
                        "X-CSRF-Token": csrf,
                        "Idempotency-Key": f"synthetic-{minutes}-{sequence}",
                    },
                )
                if response.status_code not in (200, 201, 202):
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response.json().get('code')}"
                    )
                return response.json()

            def upload(source=source, csrf=csrf):
                data = post(
                    "/api/v1/uploads",
                    {
                        "size_bytes": source["bytes"],
                        "sha256": source["sha256"],
                        "rights_attested": True,
                    },
                )
                with (base / "media" / source["file"]).open("rb") as handle:
                    index = 0
                    while chunk := handle.read(data["part_bytes"]):
                        response = client.put(
                            f"/api/v1/uploads/{data['id']}/parts/{index}",
                            content=chunk,
                            headers={
                                "Origin": settings.public_app_url,
                                "X-CSRF-Token": csrf,
                                "Content-Type": "application/octet-stream",
                                "X-Content-SHA256": hashlib.sha256(chunk).hexdigest(),
                            },
                        )
                        if response.status_code != 200:
                            raise RuntimeError(
                                f"Part HTTP {response.status_code}: {response.json().get('code')}"
                            )
                        index += 1
                return data, post(f"/api/v1/uploads/{data['id']}/complete")

            accepted_at = time.monotonic()
            data, validation = measure("ASGI_HTTP_chunked_upload", upload)

            def drive(jid, timeout):
                waits = []
                start = time.monotonic()
                while time.monotonic() - start < timeout:
                    with factory() as db:
                        job = db.get(Job, UUID(jid))
                        if job.state not in {"QUEUED", "RUNNING"}:
                            return job.state, job.error_code, waits
                    worker.dispatch(factory, redis)
                    q = Queue("ai", connection=redis)
                    qr = Queue("render", connection=redis)
                    for queue in (q, qr):
                        for item in queue.get_jobs():
                            if item.enqueued_at:
                                waits.append(max(0, (utcnow() - item.enqueued_at).total_seconds()))
                    Worker([q, qr], connection=redis, log_job_description=False).work(
                        burst=True, logging_level="WARNING", with_scheduler=False
                    )
                raise TimeoutError("Synthetic driver deadline; runtime job timeouts unchanged")

            state, error, waits = measure(
                "validation_RQ", lambda validation=validation: drive(validation["id"], 660)
            )
            if state != "COMPLETED":
                results.append({"minutes": minutes, "state": state, "error": error})
                continue
            quote = post(
                "/api/v1/jobs/quote",
                {"source_seconds": minutes * 60, "output_count": 3, "edit_count": 1},
            )
            job = post(
                f"/api/v1/videos/{data['video_id']}/generate",
                {"quote_id": quote["id"], "auto_render": True},
            )
            state, error, processing_waits = measure(
                "processing_RQ",
                lambda job=job, minutes=minutes: drive(job["id"], minutes * 60 + 900),
            )
            if (base / "pressure-result.json").exists():
                pressure.update(json.loads((base / "pressure-result.json").read_text()))
            if pressure_future is not None and minutes == 5:
                try:
                    result = pressure_future.result(timeout=300)
                    pressure.update(result="PASS", output_bytes=result["size_bytes"])
                except Exception as exc:
                    pressure.update(
                        result="FAIL", error_code=getattr(exc, "code", type(exc).__name__)
                    )
            with factory() as db:
                wallet = db.scalar(select(Wallet).where(Wallet.user_id == users[minutes]))
                outputs = list(
                    db.scalars(select(RenderOutput).where(RenderOutput.job_id == UUID(job["id"])))
                )
                retained = db.scalar(
                    select(func.sum(StorageObject.materialized_bytes)).where(
                        StorageObject.deleted.is_(False)
                    )
                )
                before = (wallet.available, wallet.reserved)
            # Idempotent cancellation after failure must not create an extra grant.
            if state == "FAILED":
                with factory() as db:
                    service.cancel_job(db, users[minutes], UUID(job["id"]))
                    service.cancel_job(db, users[minutes], UUID(job["id"]))
                    db.commit()
                with factory() as db:
                    w = db.scalar(select(Wallet).where(Wallet.user_id == users[minutes]))
                    assert before == (w.available, w.reserved) == (3700, 0)
            with factory() as db:
                transcript = db.scalar(
                    select(Transcript).where(Transcript.job_id == UUID(job["id"]))
                )
                local_ids = list(
                    db.scalars(
                        select(AIRequest.id).where(
                            AIRequest.job_id == UUID(job["id"]), AIRequest.provider == "whisper"
                        )
                    )
                )
                receipt_bytes = sum(
                    storage.path(rid).stat().st_size
                    for rid in local_ids
                    if storage.path(rid).exists()
                )
                transcript_stats = (
                    None
                    if transcript is None
                    else {
                        "words": len(transcript.data["words"]),
                        "first_start": transcript.data["words"][0]["start"]
                        if transcript.data["words"]
                        else None,
                        "last_end": transcript.data["words"][-1]["end"]
                        if transcript.data["words"]
                        else None,
                        "duration_seconds": transcript.data["duration_seconds"],
                    }
                )
            row = {
                "local_chunks": len(local_ids),
                "local_receipt_bytes": receipt_bytes,
                "transcript_stats": transcript_stats,
                "minutes": minutes,
                "state": state,
                "error": error,
                "accepted_to_terminal_seconds": time.monotonic() - accepted_at,
                "quote_credits": quote["credits"],
                "wallet_available": before[0],
                "wallet_reserved": before[1],
                "outputs": len(outputs),
                "output_bytes": sum(o.metadata_json.get("size_bytes", 0) for o in outputs),
                "retained_materialized_bytes_all_cases": int(retained or 0),
                "queue_wait_samples_seconds": waits + processing_waits,
            }
            results.append(row)
            (base / f"result-{minutes}.json").write_text(json.dumps(row, indent=2))
            if state != "COMPLETED":
                break  # Diagnose the failed duration before starting a longer run.
    pool.shutdown()
    # Real RQ work horses fork; child measurements are fsynced to this shared log,
    # not retained in the controller's private Python list.
    phases = [json.loads(line) for line in (base / "phases.jsonl").read_text().splitlines()]
    memory = Path("/sys/fs/cgroup/memory.peak")
    result = {
        "synthetic": True,
        "queue_worker": "RQ Worker with forked work horses (production class)",
        "real_provider_verified": False,
        "paid_calls": 0,
        "ASGI_upload_not_external_bandwidth": True,
        "results": results,
        "phases": phases,
        "concurrent_pressure": pressure
        or {
            "result": next(
                (p["result"] for p in phases if p["stage"] == "concurrent_90s_render"), "UNVERIFIED"
            ),
            "output_bytes": (base / "pressure-render.mp4").stat().st_size
            if (base / "pressure-render.mp4").exists()
            else 0,
            "from_prior_completed_case": True,
        },
        "resumed_without_repeating_completed_jobs": resume,
        "container_peak_memory_bytes": int(memory.read_text()) if memory.exists() else None,
        "phase_cpu_overlap": "Concurrent phase CPU overlaps; do not sum render and inference CPU",
        "activation_allowed": False,
    }
    (base / "acceptance.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"finished": True, "states": [(r["minutes"], r["state"]) for r in results]}))


if __name__ == "__main__":
    run(Path(sys.argv[1]))
