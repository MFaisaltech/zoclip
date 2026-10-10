"""Isolated development Compose only: actual API -> outbox -> RQ -> ffprobe.

Leaves immutable fictional audit/job history in the disposable project database.
Never run against a deployment or shared customer database.
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from zoclip.auth.models import AuthSession, User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits.models import Plan
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput
from zoclip.credits.service import configure_plan
from zoclip.media.models import SourceVideo, StorageObject


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.app_env != "development" or os.environ.get("ZOCLIP_ISOLATED_SMOKE") != "1":
        raise RuntimeError("Explicit isolated development smoke opt-in required")
    engine = build_engine(settings.database_url.get_secret_value())
    raw, csrf = uuid4().hex, uuid4().hex
    with Session(engine) as db:
        staff = User(email=f"smoke-staff-{uuid4()}@example.invalid", verified=True, role="admin")
        owner = User(email=f"smoke-media-{uuid4()}@example.invalid", verified=True)
        db.add_all([staff, owner])
        db.flush()
        owner_id = owner.id
        plan = db.scalar(select(Plan).where(Plan.slug == "free"))
        configure_plan(
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
                reason="Explicit isolated fictional ingestion smoke",
            ),
            uuid4().hex,
            staff.id,
        )
        db.add(
            AuthSession(
                user_id=owner.id,
                token_hash=digest(raw),
                csrf_hash=digest(csrf),
                expires_at=utcnow() + timedelta(minutes=10),
            )
        )
        db.commit()

    def api(
        path: str, method: str = "GET", body: dict | bytes | None = None, extra: dict | None = None
    ) -> bytes:
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
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()

    video_id = None
    import_ids: list[UUID] = []
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x240:rate=25",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=16000",
                    "-t",
                    "2.5",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "1",
                    "-crf",
                    "16",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "64k",
                    "-movflags",
                    "+faststart",
                    str(path),
                ],
                check=True,
                timeout=30,
                shell=False,
            )
            content = path.read_bytes()
        upload = json.loads(
            api(
                "/uploads",
                "POST",
                {
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "rights_attested": True,
                },
            )
        )
        video_id = UUID(upload["video_id"])
        for number, start in enumerate(range(0, len(content), upload["part_bytes"])):
            part = content[start : start + upload["part_bytes"]]
            api(
                f"/uploads/{upload['id']}/parts/{number}",
                "PUT",
                part,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
                },
            )
        job = json.loads(api(f"/uploads/{upload['id']}/complete", "POST"))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status = json.loads(api(f"/jobs/{job['id']}"))
            if status["state"] in {"COMPLETED", "FAILED", "CANCELED"}:
                break
            time.sleep(0.5)
        assert status["state"] == "COMPLETED", status["error_code"]
        assert api(f"/videos/{video_id}/content") == content
        metadata = json.loads(api(f"/videos/{video_id}"))["metadata_json"]
        assert metadata["duration_seconds"] == 3 and metadata["size_bytes"] == len(content)
        print("Actual chunk API/outbox/Linux RQ/constrained ffprobe/private download: PASS")
        if os.environ.get("ZOCLIP_HTTPS_SMOKE") == "1":
            base = os.environ["HTTPS_FIXTURE_URL"].rstrip("/")
            expected = Path(os.environ["HTTPS_FIXTURE_PATH"]).read_bytes()
            for suffix, cap, error in (
                ("/source.mp4", len(expected), None),
                ("/redirect", len(expected), None),
                ("/wrong-mime", len(expected), "invalid_media"),
                ("/source.mp4", 10, "media_too_large"),
                ("/private-redirect", len(expected), "unsupported_source"),
            ):
                imported = json.loads(
                    api(
                        "/videos/import-url",
                        "POST",
                        {"url": base + suffix, "max_bytes": cap, "rights_attested": True},
                    )
                )
                import_ids.append(UUID(imported["video_id"]))
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    state = json.loads(api(f"/jobs/{imported['id']}"))
                    if state["state"] in {"COMPLETED", "FAILED", "CANCELED"}:
                        break
                    time.sleep(0.5)
                if error:
                    assert state["state"] == "FAILED" and state["error_code"] == error, state
                else:
                    assert state["state"] == "COMPLETED", state
                    assert api(f"/videos/{imported['video_id']}/content") == expected
            print(
                "Actual HTTPS API/outbox/RQ/TLS import + redirect/MIME/size/private-redirect: PASS"
            )
    finally:
        for imported_id in import_ids:
            api(f"/videos/{imported_id}", "DELETE")
        if video_id:
            api(f"/videos/{video_id}", "DELETE")
        with Session(engine) as db:
            for session in db.scalars(select(AuthSession).where(AuthSession.user_id == owner_id)):
                session.revoked_at = utcnow()
            db.get(User, owner_id).status = "disabled"
            db.commit()
    if video_id:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with Session(engine) as db:
                video = db.get(SourceVideo, video_id)
                if db.get(StorageObject, video.object_id).deleted:
                    print("Lease-safe private file cleanup/capacity restoration: PASS")
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("Maintenance did not remove smoke media")
    engine.dispose()


if __name__ == "__main__":
    main()
