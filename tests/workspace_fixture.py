"""Synthetic listing fixtures; no media files, outbox, paid calls or payments."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from zoclip.ai.models import ClipSuggestion  # noqa: F401 - register nullable foreign-key table
from zoclip.auth.models import User
from zoclip.core.db import utcnow
from zoclip.core.security import hash_password
from zoclip.credits import service as credits
from zoclip.credits.models import Plan
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput
from zoclip.media.models import Job, Project, SourceVideo, StorageObject
from zoclip.rendering.models import Clip, ClipRevision

PASSWORD = "Disposable workspace test password 47!"
REASON = "Explicit synthetic workspace verification fixture"


def seed_workspace(factory):
    """Caller must supply a disposable test DB or rollback fixture session."""
    with factory() as db:
        suffix = uuid4().hex
        staff = User(email=f"workspace-staff-{suffix}@example.com", verified=True, role="admin")
        users = {
            name: User(
                email=f"workspace-{name}-{suffix}@example.com",
                verified=True,
                password_hash=hash_password(PASSWORD),
            )
            for name in ("alice", "bob")
        }
        db.add_all([staff, *users.values()])
        db.flush()
        plan = db.scalar(select(Plan).where(Plan.slug == "creator"))
        rules = ConsumptionRules(
            credits_per_minute=1,
            credits_per_output=0,
            credits_per_edit=0,
            captions_credits=0,
            reframe_credits=0,
            max_source_seconds=7200,
            max_outputs=10,
            max_edits=5,
            max_concurrent_jobs=1,
            daily_credits=1000,
            monthly_credits=10000,
        )
        version = credits.configure_plan(
            db,
            plan.id,
            PlanVersionInput(
                price_paisa=12345,
                included_credits=12,
                valid_days=30,
                rules=rules,
                reason=REASON,
            ),
            suffix,
            staff.id,
        )
        result = {}
        now = utcnow()
        for name, user in users.items():
            credits.adjust(
                db,
                user.id,
                1234 if name == "alice" else 47,
                "fixture-grant",
                staff.id,
                REASON,
                grant=True,
            )
            if name == "alice":
                for i in range(21):
                    credits.grant_entitlement(
                        db, user.id, version.id, f"fixture-entitlement-{i}", staff.id, REASON
                    )
                for i in range(20):
                    credits.adjust(db, user.id, 1, f"fixture-adjust-{i}", staff.id, REASON)
            rows = {"videos": [], "jobs": [], "clips": []}
            for i in range(23 if name == "alice" else 1):
                created = now - timedelta(seconds=i)
                project = Project(user_id=user.id)
                storage = StorageObject(user_id=user.id, reserved_bytes=0, materialized_bytes=0)
                db.add_all([project, storage])
                db.flush()
                video = SourceVideo(
                    user_id=user.id,
                    project_id=project.id,
                    object_id=storage.id,
                    state="DELETED" if i == 22 else "READY",
                    metadata_json={},
                    expires_at=now + timedelta(days=7) if i != 21 else now - timedelta(days=1),
                    created_at=created,
                )
                db.add(video)
                db.flush()
                job = Job(
                    user_id=user.id,
                    video_id=video.id,
                    operation_key=f"fixture-job-{i}",
                    request_hash="0" * 64,
                    kind="PROCESS",
                    state="SUGGESTIONS_READY",
                    checkpoint={"estimated_credits": 3},
                    created_at=created,
                    payload={"private_fixture_value": "must never be serialized"},
                )
                db.add(job)
                db.flush()
                clip = Clip(
                    user_id=user.id,
                    video_id=video.id,
                    job_id=job.id,
                    created_at=created,
                    revision=1,
                )
                db.add(clip)
                db.flush()
                db.add(
                    ClipRevision(
                        clip_id=clip.id,
                        number=1,
                        preferences={
                            "start_ms": 1000,
                            "end_ms": 13000,
                            "title": f"Workspace fixture {name.title()} {i:02d}",
                        },
                    )
                )
                rows["jobs"].append(str(job.id))
                if i < 21:
                    rows["videos"].append(str(video.id))
                    rows["clips"].append(str(clip.id))
            wallet = credits.lock_wallet(db, user.id)
            result[name] = {
                "id": str(user.id),
                "email": user.email,
                "available_credits": wallet.available,
                **rows,
            }
        db.commit()
        return {"users": result, "password": PASSWORD, "price_version_id": str(version.id)}
