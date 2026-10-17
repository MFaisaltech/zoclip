"""Approved local-only admin/financial preparation; never opens the breaker or AI."""

import argparse
import getpass
import json
import logging
import os
import secrets
import socket
import subprocess
import threading
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from zoclip.auth.models import AuditLog, User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.credits.models import CreditTransaction, Plan, SystemLimits, Wallet
from zoclip.main import create_app
from zoclip.ops.local_bootstrap import (
    Approval,
    financial_payloads,
    isolated,
    promote,
    verified_batch_model,
    verify_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "var/live-ai-readiness/acceptance-admin"
PROPOSAL = ROOT / "docs/ONE_SHOT_APPROVAL_SHEET.md"
APPROVED_SHA256 = "8bf64d70607771ec0f5b4a941761dc0a500af5d719c212d4c48b46f996e3dec5"
ADDENDUM = ROOT / "docs/PROVIDER_COMPATIBILITY_ADDENDUM.md"
AMENDMENT_SHA256 = "64f9c68be9ed6dacea7dae9cc7b6adbec0ff66795337bdfc1f1454d1daa11ef0"
CUSTOMER = ROOT / "var/live-ai-readiness/acceptance-account/account.json"
PLAN = {
    "price_paisa": 0,
    "included_credits": 0,
    "valid_days": 0,
    "approved": False,
    "rules": {
        "credits_per_minute": 1,
        "credits_per_output": 0,
        "credits_per_edit": 0,
        "captions_credits": 0,
        "reframe_credits": 0,
        "max_source_seconds": 30,
        "max_outputs": 1,
        "max_edits": 0,
        "max_concurrent_jobs": 1,
        "daily_credits": 1,
        "monthly_credits": 1,
    },
    "reason": "Isolated one-shot acceptance; no commercial pricing approval",
}
CREDIT = {"amount": 1, "reason": "One isolated 27-second acceptance job; one output only"}


def private_directory() -> None:
    if os.name != "nt":
        raise ValueError("Windows local operator command required")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
    ).stdout
    import csv

    sid = next(csv.reader([identity.strip()]))[1]
    subprocess.run(
        [
            "icacls",
            str(PRIVATE),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
        ],
        capture_output=True,
        check=True,
    )


def exclusive(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def loopback_only():  # type: ignore[no-untyped-def]
    connect, dns = socket.socket.connect, socket.getaddrinfo
    socketpair = socket.socketpair
    internal = threading.local()

    def local_pair(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Windows asyncio creates an internal loopback socketpair on an ephemeral
        # port. Permit only that synchronous implementation, on its own thread.
        internal.socketpair = True
        try:
            return socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False

    def restricted(sock, address):  # type: ignore[no-untyped-def]
        if (
            isinstance(address, tuple)
            and address[0] in {"127.0.0.1", "::1"}
            and (address[1] in {55439, 56389} or getattr(internal, "socketpair", False))
        ):
            return connect(sock, address)
        raise ValueError("Non-readiness network connection blocked")

    def local_dns(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host in {"127.0.0.1", "localhost", "::1"}:
            return dns(host, *args, **kwargs)
        raise ValueError("External DNS blocked")

    socket.socket.connect = restricted  # type: ignore[method-assign]
    socket.getaddrinfo = local_dns  # type: ignore[assignment]
    socket.socketpair = local_pair
    try:
        yield
    finally:
        socket.socket.connect, socket.getaddrinfo = connect, dns  # type: ignore[method-assign]
        socket.socketpair = socketpair


def checked(response, expected: int = 200):  # type: ignore[no-untyped-def]
    if response.status_code != expected:
        # Never print provider/auth/DB payloads, credentials or private request bodies.
        raise ValueError(f"Local application refused request: HTTP {response.status_code}")
    return response.json()


def login(client: TestClient, account: dict, origin: str) -> dict:
    csrf = checked(client.get("/api/v1/auth/csrf"))["csrf_token"]
    result = checked(
        client.post(
            "/api/v1/auth/login",
            json={k: account[k] for k in ("email", "password")},
            headers={"Origin": origin, "X-CSRF-Token": csrf},
        )
    )
    return {"Origin": origin, "X-CSRF-Token": result["csrf_token"]}


def preflight(db, customer_id: UUID) -> None:  # type: ignore[no-untyped-def]
    if db.scalar(text("SELECT version_num FROM alembic_version")) != (
        ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    ):
        raise ValueError("Current migrations required")
    system = db.get(SystemLimits, 1)
    customer = db.get(User, customer_id)
    if (
        not system
        or not system.breaker
        or not customer
        or customer.role != "customer"
        or not customer.verified
        or customer.status != "active"
    ):
        raise ValueError("Open breaker and existing verified customer required")
    for table in ("jobs", "ai_requests", "spend_attempts", "provider_usage"):
        if db.scalar(text(f"SELECT count(*) FROM {table}")):
            raise ValueError("Unexpected work/expense history; stop for review")


def run(phase: str, settings: Settings) -> None:
    isolated(settings)
    if sha256(PROPOSAL.read_bytes()).hexdigest() != APPROVED_SHA256:
        raise ValueError("Proposal differs from approved version; stop for approval")
    if any(
        os.environ.get(k)
        for k in ("TEST_DATABASE_URL", "ZOCLIP_PROVIDER_SIMULATOR", "ZOCLIP_ALLOW_PAID_ACCEPTANCE")
    ):
        raise ValueError("Test/paid process overrides forbidden")
    private_directory()
    customer_id = UUID(json.loads(CUSTOMER.read_text())["user_id"])
    engine = build_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as db:
            preflight(db, customer_id)
            if phase == "bootstrap":
                admins = list(db.scalars(select(User).where(User.role == "admin")))
                if admins:
                    manifest = PRIVATE / "approval.json"
                    if not manifest.exists():
                        raise ValueError("Admin already exists; no new registration permitted")
                    prior = Approval.model_validate_json(manifest.read_text())
                    events = list(
                        db.scalars(
                            select(AuditLog).where(AuditLog.action == "ops.local_admin_bootstrap")
                        )
                    )
                    if (
                        len(admins) != 1
                        or admins[0].id != prior.admin_id
                        or len(events) != 1
                        or events[0].request_id != str(prior.operation_id)
                    ):
                        raise ValueError("Existing bootstrap differs; stop for review")
        app_settings = settings.model_copy(
            update={
                "email_mode": "development",
                "dev_mailbox_dir": str(PRIVATE / "mailbox"),
            }
        )
        app = create_app(app_settings)
        with TestClient(app, base_url="https://localhost") as client:
            if not app.state.redis.ping():
                raise ValueError("Redis unavailable")
            if phase == "bootstrap":
                account_path = PRIVATE / "account.json"
                if not account_path.exists():
                    exclusive(
                        account_path,
                        {
                            "email": f"acceptance-admin-{uuid4().hex}@example.com",
                            "password": secrets.token_urlsafe(32),
                        },
                    )
                account = json.loads(account_path.read_text())
                with factory() as db:
                    user = db.scalar(select(User).where(User.email == account["email"]))
                if user is None or not user.verified:
                    csrf = checked(client.get("/api/v1/auth/csrf"))["csrf_token"]
                    headers = {"Origin": settings.public_app_url, "X-CSRF-Token": csrf}
                    checked(
                        client.post("/api/v1/auth/register", json=account, headers=headers), 202
                    )
                    messages = [
                        json.loads(p.read_text()) for p in (PRIVATE / "mailbox").glob("*.json")
                    ]
                    tokens = [
                        m["token"]
                        for m in messages
                        if m["recipient"] == account["email"] and m["purpose"] == "verify-email"
                    ]
                    if len(tokens) != 1:
                        raise ValueError("Ambiguous mailbox; stop without another account")
                    checked(
                        client.post(
                            "/api/v1/auth/verify-email", json={"token": tokens[0]}, headers=headers
                        )
                    )
                headers = login(client, account, settings.public_app_url)
                admin_id = UUID(checked(client.get("/api/v1/me"))["id"])
                manifest = PRIVATE / "approval.json"
                if not manifest.exists():
                    approval = Approval(
                        operation_id=uuid4(),
                        admin_id=admin_id,
                        customer_id=customer_id,
                        operator=getpass.getuser(),
                        approved_at=utcnow(),
                        reason="Approved isolated first-admin provisioning for one-shot acceptance",
                        approval_evidence="User explicitly approved audited local-only bootstrap "
                        "and isolated configuration exactly as approval sheet",
                        proposal_sha256=sha256(PROPOSAL.read_bytes()).hexdigest(),
                    )
                    exclusive(manifest, approval.model_dump(mode="json"))
                approval = Approval.model_validate_json(manifest.read_text())
                verify_manifest(approval, PROPOSAL)
                if approval.admin_id != admin_id or approval.customer_id != customer_id:
                    raise ValueError("Manifest account binding mismatch")
                with factory() as db:
                    preflight(db, customer_id)
                    audit_id = promote(db, approval)
                    db.commit()
                if client.get("/api/v1/me").status_code != 401:
                    # On a replay login is new; revoke through ordinary logout, not promotion.
                    checked(client.post("/api/v1/auth/logout", headers=headers))
                headers = login(client, account, settings.public_app_url)
                if checked(client.get("/api/v1/me"))["role"] != "admin":
                    raise ValueError("Fresh admin login failed")
                checked(client.post("/api/v1/auth/logout", headers=headers))
                receipt = PRIVATE / "bootstrap-receipt.json"
                if not receipt.exists():
                    exclusive(receipt, {"audit_id": str(audit_id), "admin_id": str(admin_id)})
                print("PASS: audited local admin; customer unchanged; fresh admin login/logout.")
                return
            approval = Approval.model_validate_json((PRIVATE / "approval.json").read_text())
            verify_manifest(approval, PROPOSAL)
            account = json.loads((PRIVATE / "account.json").read_text())
            headers = login(client, account, settings.public_app_url)
            try:
                if UUID(checked(client.get("/api/v1/me"))["id"]) != approval.admin_id:
                    raise ValueError("Authenticated admin differs from approved manifest")
                if phase == "plan-credit":
                    with factory() as db:
                        preflight(db, customer_id)
                        plan = db.scalars(
                            select(Plan).where(Plan.slug == "free", Plan.enabled)
                        ).one()
                        plan_id = plan.id
                        wallet = db.scalar(select(Wallet).where(Wallet.user_id == customer_id))
                        entries = list(
                            db.scalars(
                                select(CreditTransaction).where(
                                    CreditTransaction.user_id == customer_id
                                )
                            )
                        )
                        if entries:
                            if (
                                len(entries) != 1
                                or entries[0].operation_key != "acceptance-v1-credit"
                                or entries[0].operation != "ADMIN_ADJUST"
                                or entries[0].available_delta != 1
                                or not wallet
                                or (wallet.available, wallet.reserved) != (1, 0)
                            ):
                                raise ValueError("Unexpected ledger; no automatic repair")
                        elif wallet and (wallet.available, wallet.reserved) != (0, 0):
                            raise ValueError("Initial customer credit balance is not zero")
                    checked(
                        client.post(
                            f"/api/v1/admin/plans/{plan_id}/versions",
                            json=PLAN,
                            headers={**headers, "Idempotency-Key": "acceptance-v1-plan"},
                        )
                    )
                    checked(
                        client.post(
                            f"/api/v1/admin/users/{customer_id}/credit-adjustments",
                            json=CREDIT,
                            headers={**headers, "Idempotency-Key": "acceptance-v1-credit"},
                        )
                    )
                    print("PASS: reviewed free-plan version; exactly one audited test credit.")
                else:
                    if sha256(ADDENDUM.read_bytes()).hexdigest() != AMENDMENT_SHA256:
                        raise ValueError("Approved Gemini amendment changed")
                    amendment = Approval.model_validate_json(
                        (PRIVATE / "amendment-2026-10-14.json").read_text()
                    )
                    verify_manifest(amendment, ADDENDUM)
                    if (
                        amendment.admin_id != approval.admin_id
                        or amendment.customer_id != customer_id
                        or amendment.operation_id == approval.operation_id
                    ):
                        raise ValueError("Amendment is not bound to the existing accounts")
                    evidence_path = PRIVATE / "provider-evidence.json"
                    if not evidence_path.exists():
                        raise ValueError(
                            "Provider account/rate/version evidence absent; no rate writes"
                        )
                    evidence = json.loads(evidence_path.read_text())
                    metadata = (PRIVATE / "deepgram-models-response.json").read_bytes()
                    selected = verified_batch_model(json.loads(metadata))
                    if (
                        evidence.get("metadata_sha256") != sha256(metadata).hexdigest()
                        or evidence.get("deepgram_version") != selected["version"]
                        or evidence.get("model_uuid") != selected["uuid"]
                    ):
                        raise ValueError("Version evidence differs from returned public metadata")
                    rates, policy = financial_payloads(settings, evidence)
                    ids = []
                    for rate in rates:
                        result = checked(
                            client.post(
                                "/api/v1/admin/cost-rates",
                                json=rate,
                                headers={
                                    **headers,
                                    "Idempotency-Key": "acceptance-v1-rate-" + rate["component"],
                                },
                            )
                        )
                        ids.append(result["id"])
                    policy["limits"]["rate_ids"] = ids
                    checked(
                        client.post(
                            "/api/v1/admin/limits/versions",
                            json=policy,
                            headers={**headers, "Idempotency-Key": "acceptance-v1-policy-closed"},
                        )
                    )
                    print("PASS: five approved rates and USD 0.05 policy; breaker remains open.")
            finally:
                checked(client.post("/api/v1/auth/logout", headers=headers))
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", required=True, choices=["bootstrap", "plan-credit", "rates-policy"]
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        with loopback_only():
            run(args.phase, Settings())  # type: ignore[call-arg]
    except Exception as exc:
        print("STOP: " + type(exc).__name__)
        raise SystemExit(1) from None
