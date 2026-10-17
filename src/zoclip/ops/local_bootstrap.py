"""Local operator bootstrap primitives; deliberately absent from HTTP routers."""

import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from zoclip.ai.worker import deepgram_rate_label
from zoclip.auth.models import AuditLog, AuthSession, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.credits.models import SystemLimits

ACTION = "ops.local_admin_bootstrap"


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    admin_id: UUID
    customer_id: UUID
    operator: str = Field(min_length=1)
    reason: str = Field(min_length=5)
    approved_at: datetime
    approval_evidence: str = Field(min_length=20)
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def isolated(settings: Settings) -> None:
    db = make_url(settings.database_url.get_secret_value())
    redis = make_url(settings.redis_url.get_secret_value())
    if (
        settings.app_env != "development"
        or settings.ai_enabled
        or (db.drivername, db.host, db.port, db.database)
        != ("postgresql+psycopg", "127.0.0.1", 55439, "zoclip_live_readiness")
        or (redis.host, redis.port, redis.database) != ("127.0.0.1", 56389, "0")
        or Path(settings.media_root).resolve() != Path("F:/ZoClip-LiveAI/media").resolve()
    ):
        raise ValueError("Disabled isolated local readiness environment required")


def promote(db: Session, approval: Approval) -> UUID:
    """Caller commits audit, promotion and session revocation in ONE transaction."""
    system = db.scalars(select(SystemLimits).where(SystemLimits.id == 1).with_for_update()).one()
    if not system.breaker:
        raise ValueError("Circuit breaker must remain open")
    if approval.admin_id == approval.customer_id:
        raise ValueError("Acceptance customer cannot be promoted")
    # Consistent lock order, also serializes approved command replays.
    users = {
        u.id: u
        for u in db.scalars(
            select(User)
            .where(User.id.in_([approval.admin_id, approval.customer_id]))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    if len(users) != 2 or any(not u.verified or u.status != "active" for u in users.values()):
        raise ValueError("Two distinct verified active accounts required")
    admin, customer = users[approval.admin_id], users[approval.customer_id]
    if customer.role != "customer":
        raise ValueError("Acceptance account must remain a customer")
    admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    prior = list(db.scalars(select(AuditLog).where(AuditLog.action == ACTION)))
    if prior:
        if (
            len(prior) == 1
            and prior[0].request_id == str(approval.operation_id)
            and prior[0].target_id == admin.id
            and prior[0].actor_id is None
            and admin.role == "admin"
            and admins == 1
        ):
            return prior[0].id
        raise ValueError("Ambiguous bootstrap history; manual review required")
    if admins or admin.role != "customer":
        raise ValueError("Bootstrap only permits the first admin")
    # Approval targets an account created by the ordinary audited auth workflows.
    for action in ("auth.verification_requested", "auth.email_verified", "auth.login"):
        if not db.scalar(
            select(AuditLog.id).where(AuditLog.target_id == admin.id, AuditLog.action == action)
        ):
            raise ValueError("Normal registration, verification and login evidence required")
    admin.role = "admin"
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == admin.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    event = AuditLog(
        actor_id=None, action=ACTION, target_id=admin.id, request_id=str(approval.operation_id)
    )
    db.add(event)
    db.flush()
    return event.id


def verify_manifest(approval: Approval, proposal: Path) -> None:
    if approval.proposal_sha256 != sha256(proposal.read_bytes()).hexdigest():
        raise ValueError("Reviewed proposal changed; stop for approval")
    if approval.approved_at.tzinfo is None or approval.approved_at > utcnow():
        raise ValueError("Approval must have a nonfuture timezone-aware timestamp")


def verified_batch_model(record: dict) -> dict:
    """Select the newest fixed general/monolingual English batch record, never an alias."""
    if record.get("status") != 200:
        raise ValueError("Public metadata request did not succeed")
    candidates = []
    for row in record.get("body", {}).get("stt", []):
        version = row.get("version", "")
        if (
            row.get("name") == "general"
            and row.get("canonical_name") == "nova-3-general"
            and row.get("architecture") == "nova-3"
            and row.get("batch") is True
            and row.get("multilingual") is False
            and "en" in row.get("languages", [])
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", version)
        ):
            date, revision = version.split(".")
            rank = datetime.strptime(date, "%Y-%m-%d"), int(revision)
            UUID(row["uuid"])
            candidates.append((rank, row))
    if not candidates:
        raise ValueError("No fixed Nova-3 general monolingual English batch version")
    newest = max(rank for rank, _ in candidates)
    selected = [row for rank, row in candidates if rank == newest]
    if len(selected) != 1:
        raise ValueError("Ambiguous newest batch metadata; no version may be guessed")
    return selected[0]


def financial_payloads(settings: Settings, evidence: dict) -> tuple[list[dict], dict]:
    """No provider IO. Refuse incomplete account/rate/version evidence before writes."""
    if (
        evidence.get("rate_basis") != "approved_public_standard_prices_2026-10-14"
        or evidence.get("nova3_english_batch_confirmed") is not True
        or not evidence.get("source")
        or not evidence.get("verified_at")
        or not settings.deepgram_version
        or settings.deepgram_version.lower() in {"latest", "beta"}
        or evidence.get("deepgram_version") != settings.deepgram_version
        or settings.deepgram_model != "nova-3"
        or settings.gemini_model != "gemini-3.1-flash-lite"
        or settings.deepgram_language != "en"
        or settings.deepgram_diarize
        or settings.deepgram_utterances
        or not settings.deepgram_mip_opt_out
    ):
        raise ValueError("Approved rate basis and verified Nova-3 English batch version required")
    specs = (
        ("deepgram", deepgram_rate_label(settings), "minute", "0.0043", 1),
        ("gemini_input", settings.gemini_model, "token", "0.00000025", 36000),
        ("gemini_output", settings.gemini_model, "token", "0.0000015", 2048),
        ("render", "local-acceptance-cpu-assumption-v1", "cpu_second", "0.00001", 520),
        ("storage", "local-acceptance-storage-assumption-v1", "gb_day", "0.001", 1),
    )
    rates = [
        dict(
            component=component,
            model=model,
            unit=unit,
            unit_usd=price,
            max_units=maximum,
            reason="Isolated acceptance rate reviewed 2026-10-14; approved Gemini 3.1 amendment",
        )
        for component, model, unit, price, maximum in specs
    ]
    limits: dict = dict.fromkeys(
        [
            "per_job_usd",
            "user_daily_usd",
            "user_monthly_usd",
            "global_daily_usd",
            "global_monthly_usd",
        ],
        "0.05",
    )
    limits.update(
        max_open_reservations=1,
        input_tokens_per_second=1000,
        max_output_tokens=2048,
        render_cpu_seconds_per_output=520,
        storage_gb_days_per_output=1,
        max_attempts_per_job=5,
    )
    return rates, {
        "limits": limits,
        "breaker": True,
        "reason": "Install isolated USD 0.05 acceptance limits with circuit breaker open",
    }
