"""Actual API/outbox/Linux RQ/FFmpeg/HTTPS adapters; isolated simulators, never live AI."""

import hashlib
import json
import os
import time
import urllib.request
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.ai.models import AIRequest, ClipSuggestion, Transcript
from zoclip.ai.worker import deepgram_rate_label
from zoclip.auth.models import AuthSession, User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits import service as money
from zoclip.credits.models import (
    CreditReservation,
    CreditTransaction,
    Plan,
    ProviderUsage,
    SpendAttempt,
)
from zoclip.credits.schemas import (
    BudgetLimits,
    ConsumptionRules,
    PlanVersionInput,
    PolicyInput,
    RateInput,
)
from zoclip.media.models import Job, SourceVideo, StorageObject


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if (
        settings.app_env != "development"
        or os.environ.get("ZOCLIP_AI_SIMULATOR_SMOKE") != "1"
        or settings.deepgram_api_key.get_secret_value() != "synthetic-phase4-not-a-live-key"
        or settings.gemini_api_key.get_secret_value() != "synthetic-phase4-not-a-live-key"
        or settings.gemini_model != "fictional-test"
    ):
        raise RuntimeError(
            "Explicit isolated simulator configuration required, live keys forbidden"
        )
    import socket

    for host in ("api.deepgram.com", "generativelanguage.googleapis.com"):
        if {a[4][0] for a in socket.getaddrinfo(host, 443)} != {"93.184.217.10"}:
            raise RuntimeError("Provider host must resolve ONLY to the isolated simulator")
    engine = build_engine(settings.database_url.get_secret_value())
    raw, csrf = uuid4().hex, uuid4().hex
    with Session(engine) as db:
        staff = User(email=f"ai-staff-{uuid4()}@example.invalid", verified=True, role="admin")
        owner = User(email=f"ai-owner-{uuid4()}@example.invalid", verified=True)
        db.add_all([staff, owner])
        db.flush()
        owner_id, staff_id = owner.id, staff.id
        plan = db.scalar(select(Plan).where(Plan.slug == "free"))
        money.configure_plan(
            db,
            plan.id,
            PlanVersionInput(
                price_paisa=0,
                included_credits=0,
                valid_days=0,
                rules=ConsumptionRules(
                    credits_per_minute=1,
                    credits_per_output=0,
                    credits_per_edit=0,
                    captions_credits=0,
                    reframe_credits=0,
                    max_source_seconds=7200,
                    max_outputs=1,
                    max_edits=0,
                    max_concurrent_jobs=1,
                    daily_credits=10,
                    monthly_credits=10,
                ),
                reason="Isolated fictional Phase 4 simulator plan",
            ),
            uuid4().hex,
            staff_id,
        )
        rates = []
        for component, unit in [
            ("deepgram", "minute"),
            ("gemini_input", "token"),
            ("gemini_output", "token"),
            ("render", "cpu_second"),
            ("storage", "gb_day"),
        ]:
            rates.append(
                money.configure_rate(
                    db,
                    RateInput(
                        component=component,
                        unit=unit,
                        unit_usd=Decimal("0.000001"),
                        max_units=1000000,
                        model=deepgram_rate_label(settings)
                        if component == "deepgram"
                        else "fictional-test",
                        reason="Fictional simulator rates, never provider prices",
                    ),
                    uuid4().hex,
                    staff_id,
                ).id
            )
        money.configure_policy(
            db,
            PolicyInput(
                limits=BudgetLimits(
                    per_job_usd=Decimal("1"),
                    user_daily_usd=Decimal("10"),
                    user_monthly_usd=Decimal("10"),
                    global_daily_usd=Decimal("10"),
                    global_monthly_usd=Decimal("10"),
                    max_open_reservations=10,
                    rate_ids=rates,
                    input_tokens_per_second=1,
                    max_output_tokens=128,
                    render_cpu_seconds_per_output=1,
                    storage_gb_days_per_output=1,
                    max_attempts_per_job=20,
                ),
                reason="Fictional simulator budget",
            ),
            uuid4().hex,
            staff_id,
        )
        money.adjust(
            db, owner_id, 2, uuid4().hex, staff_id, "Isolated simulator test grant", grant=True
        )
        db.add(
            AuthSession(
                user_id=owner_id,
                token_hash=digest(raw),
                csrf_hash=digest(csrf),
                expires_at=utcnow() + timedelta(minutes=10),
            )
        )
        db.commit()

    def api(
        path: str, method: str = "GET", body: dict | bytes | None = None, extra: dict | None = None
    ) -> dict:
        headers = {
            "Host": urlsplit(settings.api_public_url).netloc,
            "Origin": settings.public_app_url,
            "Cookie": f"{COOKIE_NAME}={raw}",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": uuid4().hex,
        }
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = body
        headers.update(extra or {})
        request = urllib.request.Request(
            "http://localhost:8000/api/v1" + path, data=data, method=method, headers=headers
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_response = response.read()
            return json.loads(raw_response) if raw_response else {}

    def wait(job_id: str, state: str) -> dict:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = api("/jobs/" + job_id)
            if result["state"] == state:
                return result
            if result["state"] in {"FAILED", "CANCELED"}:
                raise AssertionError("Simulator job failed: " + str(result["error_code"]))
            time.sleep(0.5)
        raise AssertionError("Real RQ job failed to reach bounded outcome")

    video_id = None
    try:
        data = Path("/verify/source.mp4").read_bytes()
        upload = api(
            "/uploads",
            "POST",
            {
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "rights_attested": True,
            },
        )
        video_id = upload["video_id"]
        for number, start in enumerate(range(0, len(data), upload["part_bytes"])):
            part = data[start : start + upload["part_bytes"]]
            api(
                f"/uploads/{upload['id']}/parts/{number}",
                "PUT",
                part,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
                },
            )
        ingest = api(f"/uploads/{upload['id']}/complete", "POST")
        wait(ingest["id"], "COMPLETED")
        video = api("/videos/" + video_id)
        for _repetition in range(2):
            quote = api(
                "/jobs/quote",
                "POST",
                {
                    "source_seconds": video["metadata_json"]["duration_seconds"],
                    "output_count": 1,
                    "captions": False,
                    "reframe": False,
                },
            )
            job = api(f"/videos/{video_id}/generate", "POST", {"quote_id": quote["id"]})
            result = wait(job["id"], "SUGGESTIONS_READY")
            assert result["progress_percent"] is None
            transcript = api(f"/videos/{video_id}/transcript")
            suggestions = api(f"/videos/{video_id}/suggestions")
            assert len(transcript["data"]["words"]) == 5 and not suggestions["rendered"]
            assert len(suggestions["items"]) == 1
            with Session(engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(AIRequest)
                        .where(AIRequest.user_id == owner_id)
                    )
                    == 2
                )
                row = db.get(Job, UUID(job["id"]))
                assert db.get(CreditReservation, row.reservation_id).state == "HELD"
                wallet = money.lock_wallet(db, owner_id)
                assert (wallet.available, wallet.reserved) == (1, 1)
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(CreditTransaction)
                        .where(
                            CreditTransaction.user_id == owner_id,
                            CreditTransaction.operation == "SETTLE",
                        )
                    )
                    == 0
                )
            api("/jobs/" + job["id"] + "/cancel", "POST")
            api("/jobs/" + job["id"] + "/cancel", "POST")
            assert api("/me/credits")["available_credits"] == 2
        api("/videos/" + video_id, "DELETE")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with Session(engine) as db:
                video = db.get(SourceVideo, UUID(video_id))
                if db.get(StorageObject, video.object_id).deleted:
                    assert (
                        db.scalar(
                            select(func.count())
                            .select_from(Transcript)
                            .where(Transcript.user_id == owner_id)
                        )
                        == 0
                    )
                    assert (
                        db.scalar(
                            select(func.count())
                            .select_from(ClipSuggestion)
                            .where(ClipSuggestion.user_id == owner_id)
                        )
                        == 0
                    )
                    assert all(
                        r.response is None
                        for r in db.scalars(select(AIRequest).where(AIRequest.user_id == owner_id))
                    )
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("Privacy cleanup did not complete")
        with Session(engine) as db:
            wallet = money.lock_wallet(db, owner_id)
            assert (wallet.available, wallet.reserved) == (2, 0)
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ProviderUsage)
                    .join(SpendAttempt, SpendAttempt.id == ProviderUsage.attempt_id)
                    .where(SpendAttempt.user_id == owner_id)
                )
                == 3
            )
        print("PASS: real API/upload/outbox/Linux RQ/FFmpeg/HTTPS simulators; timings/suggestions")
        print(
            "PASS: cache reuse, three usage records, held credits/no settlement, "
            "cancel once, privacy cleanup"
        )
    finally:
        with Session(engine) as db:
            db.get(User, owner_id).status = "disabled"
            db.get(User, staff_id).status = "disabled"
            for session in db.scalars(select(AuthSession).where(AuthSession.user_id == owner_id)):
                session.revoked_at = utcnow()
            db.commit()
        engine.dispose()


if __name__ == "__main__":
    main()
