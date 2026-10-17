"""Continuation tests use only fresh preserved mock PostgreSQL schemas and fake approval."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session
from test_local_bootstrap import bootstrap_db  # noqa: F401

from zoclip.auth.models import AuditLog, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.credits.models import CostPolicy, CostRate, CreditTransaction, SystemLimits, Wallet
from zoclip.ops import acceptance_continuation as cont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def continuation(bootstrap_db, tmp_path, monkeypatch):  # noqa: F811
    factory, bootstrap, _ = bootstrap_db
    root = tmp_path / "project"
    private = root / "var/live-ai-readiness/acceptance-admin"
    private.mkdir(parents=True)
    with factory() as db:
        db.get(User, bootstrap.admin_id).role = "admin"
        rates = []
        audits = []
        for component, unit in (
            ("deepgram", "minute"),
            ("gemini_input", "token"),
            ("gemini_output", "token"),
            ("render", "cpu_second"),
            ("storage", "gb_day"),
        ):
            rate = CostRate(
                component=component,
                model="offline",
                unit=unit,
                unit_usd="0.000001",
                max_units=1,
                operation_key=component,
                payload_hash="0" * 64,
                actor_id=bootstrap.admin_id,
                reason="Explicit fictional test rate",
            )
            db.add(rate)
            db.flush()
            rates.append(rate)
            audits.append(
                AuditLog(
                    action="costs.rate_created",
                    target_id=rate.id,
                    actor_id=bootstrap.admin_id,
                    request_id=str(uuid4()),
                )
            )
        policy = CostPolicy(
            operation_key="closed",
            payload_hash="0" * 64,
            actor_id=bootstrap.admin_id,
            reason="Offline policy",
            limits={"rate_ids": [str(r.id) for r in rates], "per_job_usd": "0.05"},
        )
        db.add(policy)
        db.flush()
        db.get(SystemLimits, 1).policy_id = policy.id
        audits.append(
            AuditLog(
                action="costs.policy_created",
                target_id=policy.id,
                actor_id=bootstrap.admin_id,
                request_id=str(uuid4()),
            )
        )
        db.add_all(audits)
        db.add(Wallet(user_id=bootstrap.customer_id, available=1, reserved=0))
        db.add(
            CreditTransaction(
                user_id=bootstrap.customer_id,
                operation="ADMIN_ADJUST",
                operation_key="original-credit",
                payload_hash="0" * 64,
                available_delta=1,
                reserved_delta=0,
                available_after=1,
                reserved_after=0,
                actor_id=bootstrap.admin_id,
                reason="Explicit offline test grant",
            )
        )
        db.commit()
        receipt = {
            "policy_id": str(policy.id),
            "limits": policy.limits,
            "ledger": [["ADMIN_ADJUST", 1, 0]],
            "rates": [
                {
                    "id": str(r.id),
                    "component": r.component,
                    "model": r.model,
                    "unit": r.unit,
                    "unit_usd": str(r.unit_usd),
                    "max_units": r.max_units,
                }
                for r in rates
            ],
            "audits": [
                {
                    "id": str(a.id),
                    "action": a.action,
                    "target_id": str(a.target_id),
                    "request_id": a.request_id,
                }
                for a in audits
            ],
        }
    (private / "financial-receipt-2026-10-14.json").write_text(json.dumps(receipt))
    (private / "approval.json").write_text(bootstrap.model_dump_json())
    (private / "live-run-entered.json").write_text(json.dumps({"operation_id": str(cont.ORIGINAL)}))
    (private / "live-result.json").write_text(
        json.dumps({"live_test": "BLOCKED", "error": "resource_or_background_worker_gate"})
    )
    (root / ".env").write_text("AI_ENABLED=false\n")
    historical = [root / ".env", *private.iterdir()]
    recovery_name = "environment-recovery-offline.json"
    (private / recovery_name).write_text(
        json.dumps(
            {
                "protected_files_sha256": {
                    str(p): sha256(p.read_bytes()).hexdigest() for p in historical
                }
            }
        )
    )
    monkeypatch.setattr(
        cont,
        "PINS",
        {
            n: sha256((private / n).read_bytes()).hexdigest()
            for n in ("live-run-entered.json", "live-result.json", recovery_name)
        },
    )
    monkeypatch.setattr(cont, "implementation_digest", lambda root: "a" * 64)
    now = utcnow()
    approval = cont.ExecutionApproval(
        original_operation=cont.ORIGINAL,
        authorization_id=uuid4(),
        admin_id=bootstrap.admin_id,
        customer_id=bootstrap.customer_id,
        operator="offline-test",
        reason="Explicit fictional execution approval for offline tests only",
        approved_at=now,
        expires_at=now + timedelta(hours=1),
        evidence_sha256=cont.digest(cont.historical_evidence(root)),
        implementation_sha256="a" * 64,
        execute_original_once=True,
        allow_audited_breaker_open=True,
        allow_process_local_ai=True,
        max_calls_per_provider=1,
        max_outputs=1,
        max_credits=1,
        max_budget_usd="0.05",
    )
    yield factory, root, approval


def audit_count(factory):
    with factory() as db:
        return db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == cont.ACTION)
        )


def test_single_use_commit_precedes_mock_dispatch_and_preserves_history(continuation):
    factory, root, approval = continuation
    before = cont.historical_evidence(root)
    calls = []
    permit = cont.consume(factory, root, approval, lambda: None)
    assert audit_count(factory) == 1
    # Fake provider callbacks only after a committed authorization, no network.
    for provider in ("deepgram", "gemini"):
        calls.append(provider)
    with pytest.raises(ValueError, match="already consumed"):
        cont.consume(factory, root, approval, lambda: None)
    assert calls == ["deepgram", "gemini"]
    assert cont.historical_evidence(root) == before
    marker = json.loads((permit.out / "consumed.json").read_text())
    assert permit.secret not in (permit.out / "consumed.json").read_text()
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == cont.HASH_ACTION + cont.digest(marker))
            )
            == 1
        )
        assert db.get(SystemLimits, 1).breaker is True
        assert db.scalar(text("SELECT count(*) FROM ai_requests")) == 0


def test_concurrent_distinct_approvals_have_one_winner(continuation):
    factory, root, approval = continuation

    def attempt(_):
        candidate = approval.model_copy(update={"authorization_id": uuid4()})
        try:
            return cont.consume(factory, root, candidate, lambda: None)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        permits = list(pool.map(attempt, range(4)))
    assert sum(p is not None for p in permits) == 1
    assert audit_count(factory) == 1


@pytest.mark.parametrize(
    "point", ["directory", "partial-file", "before-commit", "commit-ack", "after-commit"]
)
def test_crash_fences_never_recover_automatically(continuation, monkeypatch, point):
    factory, root, approval = continuation
    if point in {"directory", "partial-file"}:
        out = cont.output_directory(root)
        out.mkdir()
        if point == "partial-file":
            (out / "consumed.json").write_text('{"incomplete":')
        with pytest.raises(FileExistsError):
            cont.consume(factory, root, approval, lambda: None)
        assert audit_count(factory) == 0
    elif point in {"before-commit", "commit-ack"}:

        def crash(db):
            raise KeyboardInterrupt("Offline simulated crash")

        hook = "before_commit" if point == "before-commit" else "after_commit"
        event.listen(factory.class_, hook, crash)
        try:
            with pytest.raises(KeyboardInterrupt):
                cont.consume(factory, root, approval, lambda: None)
        finally:
            event.remove(factory.class_, hook, crash)
        assert audit_count(factory) == (0 if point == "before-commit" else 1)
    else:
        cont.consume(factory, root, approval, lambda: None)
        assert audit_count(factory) == 1
    with pytest.raises((FileExistsError, ValueError)):
        cont.consume(
            factory, root, approval.model_copy(update={"authorization_id": uuid4()}), lambda: None
        )


@pytest.mark.parametrize(
    "change",
    [
        {"execute_original_once": False},
        {"allow_audited_breaker_open": False},
        {"allow_process_local_ai": False},
        {"original_operation": uuid4()},
        {"approved_at": utcnow() + timedelta(hours=1)},
        {"expires_at": utcnow() - timedelta(seconds=1)},
        {"expires_at": utcnow() + timedelta(hours=3)},
        {"evidence_sha256": "0" * 64},
        {"implementation_sha256": "0" * 64},
    ],
)
def test_unapproved_expired_or_changed_scope_cannot_consume(continuation, change):
    factory, root, approval = continuation
    with pytest.raises(ValueError):
        cont.consume(factory, root, approval.model_copy(update=change), lambda: None)
    assert not cont.output_directory(root).exists()
    assert audit_count(factory) == 0


@pytest.mark.parametrize("value", ["true", 1, None])
def test_approval_requires_strict_boolean(continuation, value):
    _, _, approval = continuation
    with pytest.raises(ValidationError):
        cont.ExecutionApproval.model_validate(
            {**approval.model_dump(), "execute_original_once": value}
        )


@pytest.mark.parametrize("table", cont.EMPTY_TABLES)
def test_every_durable_work_table_blocks_consumption(continuation, monkeypatch, table):
    factory, root, approval = continuation
    original_scalar = Session.scalar

    def scalar(db, statement, *args, **kwargs):
        if str(statement) == f"SELECT count(*) FROM {table}":
            return 1
        return original_scalar(db, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", scalar)
    with pytest.raises(ValueError, match="not empty"):
        cont.consume(factory, root, approval, lambda: None)
    assert not cont.output_directory(root).exists()


@pytest.mark.parametrize("change", ["breaker", "wallet", "account", "extra-policy"])
def test_changed_financial_or_account_state_blocks(continuation, change):
    factory, root, approval = continuation
    with factory() as db:
        if change == "breaker":
            db.get(SystemLimits, 1).breaker = False
        elif change == "wallet":
            db.scalars(select(Wallet)).one().available = 2
        elif change == "account":
            db.get(User, approval.customer_id).role = "admin"
        else:
            db.add(
                CostPolicy(
                    operation_key="different",
                    payload_hash="0" * 64,
                    limits={},
                    actor_id=approval.admin_id,
                    reason="Offline extra policy",
                )
            )
        db.commit()
    with pytest.raises(ValueError):
        cont.consume(factory, root, approval, lambda: None)
    assert audit_count(factory) == 0


@pytest.mark.parametrize("kind", ["history", "binding", "phase", "executor"])
def test_changed_history_or_existing_phase_blocks(continuation, kind):
    factory, root, approval = continuation
    private = root / "var/live-ai-readiness/acceptance-admin"
    if kind == "history":
        (private / "live-result.json").write_text("changed")
    elif kind == "binding":
        (private.parent / "acceptance-binding.json").write_text("{}")
    elif kind == "phase":
        (private.parent / "acceptance-ai-entered.json").write_text("{}")
    else:
        (private / "live-ai-executor.json").write_text("{}")
    with pytest.raises(ValueError):
        cont.consume(factory, root, approval, lambda: None)
    assert audit_count(factory) == 0


def test_resource_failure_before_and_after_lock_does_not_consume(continuation):
    factory, root, approval = continuation
    for fail_on in (1, 2):
        calls = []

        def resource(calls=calls, fail_on=fail_on):
            calls.append(1)
            if len(calls) == fail_on:
                raise ValueError("Offline resource failure")

        with pytest.raises(ValueError, match="resource"):
            cont.consume(factory, root, approval, resource)
        assert not cont.output_directory(root).exists()
        assert audit_count(factory) == 0


def test_committed_receipt_and_phase_require_audit_hash_and_in_memory_permit(
    continuation, monkeypatch
):
    import zoclip.core.db as database

    factory, root, approval = continuation
    monkeypatch.setattr(cont, "isolated", lambda settings: None)
    monkeypatch.setattr(database, "build_engine", lambda url: factory.kw["bind"])
    monkeypatch.setattr(factory.kw["bind"], "dispose", lambda: None)
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://offline/offline")
    permit = cont.consume(factory, root, approval, lambda: None)
    with pytest.raises(ValueError, match="committing process"):
        cont.begin_workflow(settings, root, cont.Permit(permit.out, "unknown-after-crash"))
    cont.begin_workflow(settings, root, permit)
    with pytest.raises(FileExistsError):
        cont.begin_workflow(settings, root, permit)
    cont.exclusive(
        permit.out / "attestation-approved.json",
        {
            "live_processing_approved": True,
            "live_operation_id": str(cont.ORIGINAL),
            "continuation_authorization_id": str(approval.authorization_id),
        },
    )
    assert cont.phase_attestation(settings, root).name == "attestation-approved.json"
    marker = json.loads((permit.out / "consumed.json").read_text())
    marker["approval"]["reason"] = "Changed after consumption for offline tamper test"
    (permit.out / "consumed.json").write_text(json.dumps(marker))
    with pytest.raises(ValueError, match="hash differs"):
        cont.phase_attestation(settings, root)


def test_stopped_continuation_cannot_enter_any_phase(continuation, monkeypatch):
    factory, root, approval = continuation
    permit = cont.consume(factory, root, approval, lambda: None)
    (permit.out / "stopped.json").write_text("{}")
    monkeypatch.setattr(cont, "isolated", lambda settings: None)
    with pytest.raises(ValueError, match="stopped"):
        cont.phase_attestation(None, root)


@pytest.mark.parametrize("failure", [None, "deepgram", "gemini"])
def test_mock_workflow_success_and_failure_never_dispatch_twice(continuation, failure):
    factory, root, approval = continuation
    calls = []

    def mock_workflow(permit):
        assert audit_count(factory) == 1
        assert (permit.out / "consumed.json").is_file()
        for provider in ("deepgram", "gemini"):
            calls.append(provider)
            if failure == provider:
                raise KeyboardInterrupt("Offline provider/process crash")

    if failure:
        with pytest.raises(KeyboardInterrupt):
            cont.execute_approved(factory, root, approval, lambda: None, mock_workflow)
    else:
        cont.execute_approved(factory, root, approval, lambda: None, mock_workflow)
    before = list(calls)
    with pytest.raises(ValueError, match="already consumed"):
        cont.execute_approved(factory, root, approval, lambda: None, mock_workflow)
    assert calls == before
    assert calls == (["deepgram"] if failure == "deepgram" else ["deepgram", "gemini"])


def test_no_callback_on_failed_commit(continuation):
    factory, root, approval = continuation
    calls = []

    def failed_commit(db):
        raise RuntimeError("Offline database commit failure")

    event.listen(factory.class_, "before_commit", failed_commit)
    try:
        with pytest.raises(RuntimeError):
            cont.execute_approved(
                factory, root, approval, lambda: None, lambda permit: calls.append("forbidden")
            )
    finally:
        event.remove(factory.class_, "before_commit", failed_commit)
    assert calls == []
    assert audit_count(factory) == 0
    assert (cont.output_directory(root) / "consumed.json").exists()


def test_replay_denied_by_database_even_with_another_filesystem_path(continuation, monkeypatch):
    factory, root, approval = continuation
    cont.consume(factory, root, approval, lambda: None)
    other = root / "another-machine-fence"
    monkeypatch.setattr(cont, "output_directory", lambda root: other)
    with pytest.raises(ValueError, match="already consumed"):
        cont.consume(factory, root, approval, lambda: None)
    assert not other.exists()


def test_inspect_cli_does_not_consume_or_import_workflow(continuation, monkeypatch, capsys):
    import continue_acceptance as cli

    factory, root, _ = continuation
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "isolated", lambda settings: None)
    monkeypatch.setattr(cli.driver, "isolated", lambda settings: None)
    monkeypatch.setattr(cli.driver, "models_ready", lambda settings: None)
    monkeypatch.setattr(cli, "implementation_digest", lambda root: "a" * 64)
    monkeypatch.setattr(sys, "argv", ["continue_acceptance.py"])
    cli.main()
    assert json.loads(capsys.readouterr().out)["consumed"] is False
    assert not cont.output_directory(root).exists()
    assert audit_count(factory) == 0


@pytest.mark.parametrize(
    "argv", [["--execute"], ["--execute", "--allow-paid"], ["--approval", "absent.json"]]
)
def test_cli_missing_explicit_execution_flags_fails_before_consumption(
    continuation, monkeypatch, argv
):
    import continue_acceptance as cli

    factory, root, _ = continuation
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "isolated", lambda settings: None)
    monkeypatch.setattr(cli.driver, "isolated", lambda settings: None)
    monkeypatch.setattr(cli.driver, "models_ready", lambda settings: None)
    monkeypatch.setattr(sys, "argv", ["continue_acceptance.py", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    assert not cont.output_directory(root).exists()
    assert audit_count(factory) == 0


@pytest.mark.parametrize(
    "ram,commit,workers", [(524287, 999999, 0), (999999, 524287, 0), (999999, 999999, 1)]
)
def test_original_resource_thresholds_are_preserved(monkeypatch, ram, commit, workers):
    from types import SimpleNamespace

    import continue_acceptance as cli

    monkeypatch.setattr(cli.shutil, "disk_usage", lambda path: SimpleNamespace(free=10**15))
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({"ram_kib": ram, "commit_kib": commit, "workers": workers})
        ),
    )
    with pytest.raises(ValueError, match="resource_or_background_worker_gate"):
        cli.resources(Settings(_env_file=None, database_url="postgresql+psycopg://offline/offline"))
