"""One pre-dispatch continuation. No grant creation, provider IO or guard reset."""

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from zoclip.auth.models import AuditLog, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.credits.models import CostPolicy, CostRate, SystemLimits, Wallet
from zoclip.ops.local_bootstrap import isolated

ORIGINAL = UUID("bb187175-59ed-425f-8c7d-bae1ff83c4aa")
ACTION = "ops.acceptance_continuation_consumed"
HASH_ACTION = "ops.cont.hash:"
PINS = {
    "../run_authorized_acceptance.py": (
        "fc395f33efad5ec9cefb5f3f1f96c3ca3ea01e09be2154029ef101311ab3f103"
    ),
    "live-run-entered.json": "671269d32ee9dcce9be4ba780a533576c86fd1803e54506905b3f9df12f7d7eb",
    "live-result.json": "4c1f92753f82db6b4f5d940f9d45b3ebf52027fdfad972eff95e2903133eb57e",
    "environment-recovery-20261014T145322130854Z.json": (
        "df7f54de84ed0a4c9dac6be99d09a4d0c08e30c7ea54202df5c47845b07f584e"
    ),
}
EMPTY_TABLES = (
    "source_videos",
    "upload_sessions",
    "upload_parts",
    "jobs",
    "job_events",
    "job_outbox",
    "ai_requests",
    "spend_attempts",
    "provider_usage",
    "credit_reservations",
    "credit_quotes",
    "transcripts",
    "clip_suggestions",
    "render_outputs",
)


class ExecutionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_operation: UUID
    authorization_id: UUID
    admin_id: UUID
    customer_id: UUID
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=20, max_length=500)
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    execute_original_once: StrictBool
    allow_audited_breaker_open: StrictBool
    allow_process_local_ai: StrictBool
    max_calls_per_provider: Literal[1]
    max_outputs: Literal[1]
    max_credits: Literal[1]
    max_budget_usd: Literal["0.05"]

    def check(self, now: datetime) -> None:
        if (
            self.original_operation != ORIGINAL
            or self.authorization_id == ORIGINAL
            or self.admin_id == self.customer_id
            or any(
                value is not True
                for value in (
                    self.execute_original_once,
                    self.allow_audited_breaker_open,
                    self.allow_process_local_ai,
                )
            )
            or not self.approved_at <= now < self.expires_at
            or self.expires_at - self.approved_at > timedelta(hours=2)
        ):
            raise ValueError("Fresh scoped execution approval required")


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exclusive(path: Path, value: object) -> None:
    """Even an empty or partial file is consumed. Never repair it automatically."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def output_directory(root: Path) -> Path:
    return root / "var/live-ai-readiness/acceptance-admin" / f"continuation-{ORIGINAL}"


@dataclass(frozen=True, repr=False)
class Permit:
    """Only the committing process receives the plaintext capability; never persisted."""

    out: Path
    secret: str


def implementation_digest(root: Path) -> str:
    names = (
        "src/zoclip/ops/acceptance_continuation.py",
        "scripts/continue_acceptance.py",
        "scripts/acceptance_continuation_workflow.py",
        "scripts/acceptance_once.py",
        "src/zoclip/ai/acceptance.py",
        "src/zoclip/ai/worker.py",
        "src/zoclip/ai/providers.py",
        "src/zoclip/credits/service.py",
        "src/zoclip/credits/schemas.py",
        "src/zoclip/core/config.py",
        "src/zoclip/media/worker.py",
        "src/zoclip/rendering/worker.py",
    )
    return digest({n: sha256((root / n).read_bytes()).hexdigest() for n in names})


def historical_evidence(root: Path) -> dict:
    private = root / "var/live-ai-readiness/acceptance-admin"
    for name, expected in PINS.items():
        if sha256((private / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Historical evidence changed")
    recovery = json.loads(
        (private / next(n for n in PINS if n.startswith("environment-"))).read_text()
    )
    pinned = recovery["protected_files_sha256"]
    if not all(
        Path(p).is_file() and sha256(Path(p).read_bytes()).hexdigest() == h
        for p, h in pinned.items()
    ):
        raise ValueError("Recovered controls or historical files changed")
    original = json.loads((private / "live-run-entered.json").read_text())
    result = json.loads((private / "live-result.json").read_text())
    if (
        original["operation_id"] != str(ORIGINAL)
        or result.get("error") != "resource_or_background_worker_gate"
        or result.get("live_test") != "BLOCKED"
    ):
        raise ValueError("Only the proven pre-dispatch failure is recoverable")
    readiness = root / "var/live-ai-readiness"
    if (
        (readiness / "acceptance-binding.json").exists()
        or list(readiness.glob("acceptance-*-entered.json"))
        or set(p.name for p in private.glob("live-*"))
        != {"live-run-entered.json", "live-result.json"}
    ):
        raise ValueError("Workflow or phase evidence already exists")
    return {
        "original_operation": str(ORIGINAL),
        "historical_sha256": PINS,
        "recovered_file_sha256": pinned,
    }


def financial_preflight(db: Session, root: Path, approval: ExecutionApproval) -> None:
    """No writes. Caller holds SystemLimits first, then the existing wallet lock."""
    private = root / "var/live-ai-readiness/acceptance-admin"
    bootstrap = json.loads((private / "approval.json").read_text())
    receipt = json.loads((private / "financial-receipt-2026-10-14.json").read_text())
    if (str(approval.admin_id), str(approval.customer_id)) != (
        bootstrap["admin_id"],
        bootstrap["customer_id"],
    ):
        raise ValueError("Existing account binding changed")
    for user_id, role in ((approval.admin_id, "admin"), (approval.customer_id, "customer")):
        user = db.get(User, user_id)
        if not user or user.role != role or not user.verified or user.status != "active":
            raise ValueError("Existing verified active account required")
    for table in EMPTY_TABLES:
        if db.scalar(text(f"SELECT count(*) FROM {table}")):
            raise ValueError("Durable work/request/expense evidence is not empty")
    if db.scalar(text("SELECT version_num FROM alembic_version")) != "7b37ea061d28":
        raise ValueError("Migration changed")
    system = db.get(SystemLimits, 1)
    policy = db.get(CostPolicy, UUID(receipt["policy_id"]))
    if (
        not system
        or system.breaker is not True
        or system.policy_id != UUID(receipt["policy_id"])
        or not policy
        or policy.limits != receipt["limits"]
        or db.scalar(select(func.count()).select_from(CostPolicy)) != 1
    ):
        raise ValueError("Closed reviewed financial policy required")
    wallet = db.scalars(
        select(Wallet).where(Wallet.user_id == approval.customer_id).with_for_update()
    ).one()
    ledger = db.execute(
        text(
            "SELECT operation,available_delta,reserved_delta "
            "FROM wallet_transactions ORDER BY created_at"
        )
    ).all()
    if [wallet.available, wallet.reserved] != [1, 0] or [list(r) for r in ledger] != receipt[
        "ledger"
    ]:
        raise ValueError("Original one-credit ledger required")
    rates = list(db.scalars(select(CostRate)))
    actual = sorted(
        (str(r.id), r.component, r.model, r.unit, str(r.unit_usd), r.max_units) for r in rates
    )
    from decimal import Decimal

    expected = sorted(
        (
            r["id"],
            r["component"],
            r["model"],
            r["unit"],
            str(Decimal(r["unit_usd"]).quantize(Decimal("0.0000000001"))),
            r["max_units"],
        )
        for r in receipt["rates"]
    )
    if actual != expected:
        raise ValueError("Reviewed rate versions changed")
    for event in receipt["audits"]:
        row = db.get(AuditLog, UUID(event["id"]))
        if (
            not row
            or row.action != event["action"]
            or str(row.target_id) != event["target_id"]
            or row.request_id != event["request_id"]
            or row.actor_id != approval.admin_id
        ):
            raise ValueError("Financial audit evidence changed")


def consume(
    factory: sessionmaker,
    root: Path,
    approval: ExecutionApproval,
    resource_check: Callable[[], None],
) -> Permit:
    """File fence precedes immutable DB audit. Any ambiguous commit stays consumed."""
    approval.check(utcnow())
    evidence = historical_evidence(root)
    if approval.evidence_sha256 != digest(
        evidence
    ) or approval.implementation_sha256 != implementation_digest(root):
        raise ValueError("Approval does not match reviewed evidence/implementation")
    resource_check()
    out = output_directory(root)
    with factory() as db:
        db.scalars(select(SystemLimits).where(SystemLimits.id == 1).with_for_update()).one()
        if db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == ACTION, AuditLog.target_id == ORIGINAL)
        ):
            raise ValueError("Continuation already consumed")
        financial_preflight(db, root, approval)
        # Recheck time, history and resources after waiting for another transaction.
        approval.check(utcnow())
        if evidence != historical_evidence(root):
            raise ValueError("Evidence changed during preflight")
        resource_check()
        # Fixed name per ORIGINAL, independent of authorization ID. Never reuse this directory.
        out.mkdir()  # An existing empty/partial directory is also a permanent fence.
        event_id = uuid4()
        secret = secrets.token_urlsafe(32)
        marker = {
            "approval": approval.model_dump(mode="json"),
            "evidence": evidence,
            "audit_id": str(event_id),
            "consumed_at": utcnow().isoformat(),
            "permit_sha256": sha256(secret.encode()).hexdigest(),
            "consuming_pid": os.getpid(),
        }
        exclusive(out / "consumed.json", marker)
        db.add(
            AuditLog(
                id=event_id,
                actor_id=approval.admin_id,
                target_id=ORIGINAL,
                action=ACTION,
                request_id=str(approval.authorization_id),
            )
        )
        # Existing action field holds the FULL SHA-256 (78 chars), append-only in PostgreSQL.
        db.add(
            AuditLog(
                actor_id=approval.admin_id,
                target_id=ORIGINAL,
                action=HASH_ACTION + digest(marker),
                request_id=str(approval.authorization_id),
            )
        )
        db.commit()  # No workflow callback can run unless this succeeds.
    return Permit(out, secret)


def committed_approval(settings: Settings, root: Path) -> ExecutionApproval:
    """Authenticate the receipt against a committed immutable authorization/hash pair."""
    isolated(settings)
    out = output_directory(root)
    if (out / "stopped.json").exists() or (out / "result.json").exists():
        raise ValueError("Continuation stopped; no phase restart permitted")
    consumed = json.loads((out / "consumed.json").read_text())
    approval = ExecutionApproval.model_validate(consumed["approval"])
    approval.check(utcnow())
    if approval.evidence_sha256 != digest(consumed["evidence"]):
        raise ValueError("Consumed historical evidence differs from approval")
    for name, expected in consumed["evidence"]["recovered_file_sha256"].items():
        if sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError("Recovered controls or historical evidence changed")
    if approval.implementation_sha256 != implementation_digest(root):
        raise ValueError("Continuation implementation changed")
    from zoclip.core.db import build_engine

    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            event = db.get(AuditLog, UUID(consumed["audit_id"]))
            if (
                not event
                or event.action != ACTION
                or event.target_id != ORIGINAL
                or event.actor_id != approval.admin_id
                or event.request_id != str(approval.authorization_id)
            ):
                raise ValueError("Committed continuation audit required")
            hashed = db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == HASH_ACTION + digest(consumed),
                    AuditLog.target_id == ORIGINAL,
                    AuditLog.actor_id == approval.admin_id,
                    AuditLog.request_id == str(approval.authorization_id),
                )
            )
            if hashed != 1:
                raise ValueError("Continuation receipt hash differs from immutable audit")
    finally:
        engine.dispose()
    return approval


def execute_approved(
    factory: sessionmaker,
    root: Path,
    approval: ExecutionApproval,
    resource_check: Callable[[], None],
    workflow: Callable[[Permit], None],
) -> None:
    """A workflow receives its nonrecoverable permit only after the audit commits."""
    permit = consume(factory, root, approval, resource_check)
    workflow(permit)


def begin_workflow(settings: Settings, root: Path, permit: Permit) -> None:
    committed_approval(settings, root)
    out = output_directory(root)
    marker = json.loads((out / "consumed.json").read_text())
    if (
        permit.out != out
        or marker["consuming_pid"] != os.getpid()
        or sha256(permit.secret.encode()).hexdigest() != marker["permit_sha256"]
    ):
        raise ValueError("Only the original committing process can start the continuation")
    exclusive(out / "workflow-entered.json", {"started_at": utcnow().isoformat()})


def phase_attestation(settings: Settings, root: Path) -> Path:
    """Keep the original phase guard, adding proof of the consumed continuation."""
    approval = committed_approval(settings, root)
    out = output_directory(root)
    if not (out / "workflow-entered.json").is_file():
        raise ValueError("Continuation workflow has not started")
    attestation = out / "attestation-approved.json"
    value = json.loads(attestation.read_text())
    if (
        value.get("live_processing_approved") is not True
        or value.get("live_operation_id") != str(ORIGINAL)
        or value.get("continuation_authorization_id") != str(approval.authorization_id)
    ):
        raise ValueError("Continuation attestation does not match audited approval")
    return attestation
