"""Focused private-staging tests; PostgreSQL cases use fresh preserved mock schemas."""

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import fakeredis
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from zoclip.auth.models import AuditLog, AuthSession, StagingInvite, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import COOKIE_NAME, digest, hash_password, verify_password
from zoclip.credits.models import CreditTransaction, SystemLimits, Wallet
from zoclip.main import create_app
from zoclip.ops import provision_staging
from zoclip.ops.staging_accounts import (
    InviteApproval,
    check_approval,
    issue,
    redeem,
    revoke,
    revoke_reviewer,
    target_hash,
)


def settings(url="postgresql+psycopg://offline:offline-only-password@db/staging_test"):
    return Settings(
        _env_file=None,
        app_env="production",
        private_staging=True,
        staging_invite_epoch="b5b2d7b5-0b59-41c5-9de0-fad66fa44d41",
        staging_site_domain="example.com",
        database_url=url,
        public_app_url="https://app.staging.example.com",
        api_public_url="https://api.staging.example.com:8443",
        allowed_hosts=["api.staging.example.com"],
        auth_rate_limit=100,
    )


def approval(config, *, actor=None, purpose="first_admin", email=None):
    return InviteApproval(
        operation_id=uuid4(),
        purpose=purpose,
        email=email or f"reviewer-{uuid4().hex}@example.com",
        actor_id=actor,
        operator="offline operator",
        identity_evidence_sha256="1" * 64,
        target_sha256=target_hash(config),
        approved_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=30),
    )


@pytest.mark.parametrize(
    "case",
    [
        "stale",
        "future",
        "naive",
        "expired",
        "too_long",
        "target",
        "actor",
        "purpose",
    ],
)
def test_reject_stale_unscoped_or_wrong_authority(case):
    # Resolve relative times at execution: a slow suite must not turn a future
    # approval collected minutes earlier into an actually valid past approval.
    now = utcnow()
    change = {
        "stale": {"approved_at": now - timedelta(minutes=16)},
        "future": {"approved_at": now + timedelta(minutes=1)},
        "naive": {"approved_at": now.replace(tzinfo=None)},
        "expired": {"expires_at": now - timedelta(seconds=1)},
        "too_long": {"expires_at": now + timedelta(hours=2)},
        "target": {"target_sha256": "f" * 64},
        "actor": {"actor_id": uuid4()},
        "purpose": {"purpose": "reviewer"},
    }[case]
    config = settings()
    with pytest.raises(ValueError):
        check_approval(config, approval(config).model_copy(update=change))


def test_approval_target_excludes_credentials_but_binds_database_and_origins():
    config = settings()
    check_approval(config, approval(config))
    assert target_hash(config) == target_hash(
        settings("postgresql+psycopg://other:rotated-password@db/staging_test")
    )
    assert target_hash(config) != target_hash(
        settings("postgresql+psycopg://offline:offline-only-password@db/other_test")
    )
    assert target_hash(config) != target_hash(
        config.model_copy(update={"staging_invite_epoch": uuid4()})
    )
    with pytest.raises(ValueError):
        check_approval(config.model_copy(update={"staging_invite_epoch": None}), approval(config))
    with pytest.raises(ValueError):
        check_approval(config.model_copy(update={"private_staging": False}), approval(config))


def test_cli_refuses_execution_without_explicit_flag(monkeypatch):
    monkeypatch.setattr(provision_staging, "Settings", settings)
    monkeypatch.setattr(sys, "argv", ["provision_staging", "issue"])
    with pytest.raises(SystemExit) as error:
        provision_staging.main()
    assert error.value.code == 2


def test_private_token_delivery_fails_closed_on_unsupported_os(monkeypatch):
    monkeypatch.setattr(provision_staging, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="Linux"):
        provision_staging.write_token(provision_staging.Path("unused-private-token"), "not-written")


@pytest.fixture
def database():
    url = os.environ.get("ZOCLIP_STAGING_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Separate mock PostgreSQL URL required")
    parsed = make_url(url)
    assert (parsed.host, parsed.port) == ("127.0.0.1", 55439)
    assert (parsed.database or "").startswith("zoclip_mock_")
    assert (parsed.database or "").endswith("_test")
    schema = "staging_invites_" + uuid4().hex
    root = create_engine(url, hide_parameters=True)
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC -c lock_timeout=5000"},
    )
    with engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    try:
        yield sessionmaker(engine, expire_on_commit=False), settings(url), engine
    finally:
        engine.dispose()
        root.dispose()  # No acceptance schema touched, no drop/downgrade/reset.


def issue_committed(factory, config, proposal):
    with factory() as db:
        value, secret = issue(db, config, proposal, "a" * 64)
        db.commit()
        return value.id, value.user_id, secret


def activate_admin(factory, config):
    operation, user, secret = issue_committed(factory, config, approval(config))
    with factory() as db:
        redeem(db, config, secret, hash_password("offline initial password"))
        db.commit()
    return user


def test_concurrent_issue_and_redeem_single_winner_and_permanent_bootstrap_close(database):
    factory, config, _ = database
    proposals = [approval(config), approval(config)]

    def issuing(proposal):
        try:
            return issue_committed(factory, config, proposal)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(issuing, proposals))
    winner = [value for value in outcomes if value]
    assert len(winner) == 1
    operation, user_id, secret = winner[0]
    with factory() as db:
        assert db.get(User, user_id).role == "customer"
        with pytest.raises(ValueError, match="already issued"):
            issue(db, config, next(p for p in proposals if p.operation_id == operation), "a" * 64)

    password = hash_password("offline initial password")

    def consuming(_):
        try:
            with factory() as db:
                redeem(db, config, secret, password)
                db.commit()
                return True
        except ApiError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consuming, range(2))) == [False, True]
    with factory() as db:
        user = db.get(User, user_id)
        assert user.verified and user.role == "admin"
        assert verify_password(user.password_hash, "offline initial password")
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "staging.first_admin_activated")
            )
            == 1
        )
        assert db.get(SystemLimits, 1).breaker is True
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 0
        assert db.scalar(select(func.count()).select_from(Wallet)) == 0
        user.role = (
            "customer"  # Test-only simulated later role removal, audit still closes bootstrap.
        )
        db.commit()
    with factory() as db, pytest.raises(ValueError, match="permanently closed"):
        issue(db, config, approval(config), "a" * 64)


def test_rollback_crash_revoke_reissue_and_immutable_evidence(database):
    factory, config, engine = database
    proposal = approval(config)
    with factory() as db:
        _, lost = issue(db, config, proposal, "a" * 64)
        db.rollback()  # Simulated crash before commit: no durable authorization/account.
    with factory() as db:
        assert db.get(StagingInvite, proposal.operation_id) is None
        with pytest.raises(ApiError):
            redeem(db, config, lost, "not-committed")
    operation, user_id, old_secret = issue_committed(factory, config, proposal)
    with factory() as db:
        redeem(db, config, old_secret, "not-committed")
        db.rollback()  # Consumption and role/password/audits roll back together.
    with factory() as db:
        assert db.get(User, user_id).verified is False
        assert db.get(StagingInvite, operation).consumed_at is None
        revoke(db, config, operation, None)
        db.commit()
    with factory() as db, pytest.raises(ApiError):
        redeem(db, config, old_secret, "not-committed")
    new_operation, same_user, secret = issue_committed(
        factory, config, approval(config, email=proposal.email)
    )
    assert same_user == user_id and new_operation != operation
    with factory() as db:
        redeem(db, config, secret, hash_password("offline recovered password"))
        db.commit()
    for query in [
        "UPDATE staging_account_invites SET consumed_at=NULL WHERE consumed_at IS NOT NULL",
        "UPDATE staging_account_invites SET purpose='reviewer' WHERE purpose='first_admin'",
        "DELETE FROM staging_account_invites",
        "TRUNCATE staging_account_invites",
    ]:
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text(query))


def test_reviewer_requires_admin_authority_does_not_escalate_and_revokes_sessions(database):
    factory, config, _ = database
    admin = activate_admin(factory, config)
    proposal = approval(config, actor=admin, purpose="reviewer")
    operation, user_id, secret = issue_committed(factory, config, proposal)
    with factory() as db:
        session = AuthSession(
            user_id=user_id,
            token_hash="2" * 64,
            csrf_hash="3" * 64,
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        session_id = session.id
    with factory() as db:
        redeem(db, config, secret, hash_password("offline reviewer password"))
        db.commit()
        assert db.get(User, user_id).role == "customer"
        assert db.get(AuthSession, session_id).revoked_at is not None
        assert db.get(StagingInvite, operation).approval_hash == "a" * 64
    with factory() as db, pytest.raises(ValueError):
        issue(db, config, approval(config, actor=user_id, purpose="reviewer"), "a" * 64)
    with factory() as db, pytest.raises(ValueError, match="Existing account"):
        issue(
            db,
            config,
            approval(config, actor=admin, purpose="reviewer", email=proposal.email),
            "a" * 64,
        )
    _, _, pending = issue_committed(
        factory, config, approval(config, actor=admin, purpose="reviewer")
    )
    with factory() as db:
        db.get(User, admin).status = "disabled"
        db.commit()
    with factory() as db, pytest.raises(ValueError):
        redeem(db, config, pending, "not-committed")


def test_expired_wrong_target_and_open_breaker_fail_closed(database):
    factory, config, _ = database
    proposal = approval(config).model_copy(update={"expires_at": utcnow() + timedelta(seconds=1)})
    operation, _, secret = issue_committed(factory, config, proposal)
    # Deterministic expiry, no sleeping or overwriting an immutable invite.
    from unittest.mock import patch

    import zoclip.ops.staging_accounts as module

    with patch.object(module, "utcnow", return_value=utcnow() + timedelta(seconds=2)):
        with factory() as db, pytest.raises(ApiError):
            redeem(db, config, secret, "not-committed")
    with factory() as db, pytest.raises(ApiError):
        redeem(
            db,
            config.model_copy(update={"public_app_url": "https://other.example.com"}),
            secret,
            "not-committed",
        )
    with factory() as db, pytest.raises(ApiError):
        redeem(
            db, config.model_copy(update={"staging_invite_epoch": uuid4()}), secret, "not-committed"
        )
    with factory() as db:
        db.get(SystemLimits, 1).breaker = False  # Isolated mock schema only.
        db.commit()
    with factory() as db, pytest.raises(ValueError):
        redeem(db, config, secret, "not-committed")
    with factory() as db, pytest.raises(ValueError):
        issue(db, config, approval(config), "a" * 64)


def test_reviewer_revocation_is_audited_idempotent_and_preserves_invite(database):
    factory, config, _ = database
    admin = activate_admin(factory, config)
    operation, user_id, raw = issue_committed(
        factory, config, approval(config, actor=admin, purpose="reviewer")
    )
    with factory() as db:
        redeem(db, config, raw, hash_password("offline revoke password"))
        session = AuthSession(
            user_id=user_id,
            token_hash="4" * 64,
            csrf_hash="5" * 64,
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        session_id = session.id
    with factory() as db, pytest.raises(ValueError):
        revoke_reviewer(db, config, operation, user_id)
    with factory() as db:
        revoke_reviewer(db, config, operation, admin)
        db.commit()
        revoke_reviewer(db, config, operation, admin)
        db.commit()
        assert db.get(User, user_id).status == "disabled"
        assert db.get(User, admin).status == "active"
        assert db.get(StagingInvite, operation).consumed_at is not None
        assert db.get(AuthSession, session_id).revoked_at is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "staging.reviewer_revoked")
            )
            == 1
        )


def test_http_invite_csrf_login_admin_and_customer_denial(database):
    factory, config, _ = database
    _, _, secret = issue_committed(factory, config, approval(config))
    app = create_app(config)
    app.state.session_factory = factory
    app.state.redis = fakeredis.FakeRedis()
    client = TestClient(
        app, base_url=config.api_public_url
    )  # No lifespan/remote startup connection.
    payload = {"token": secret, "password": "offline web password"}
    assert client.post("/api/v1/auth/invite/accept", json=payload).status_code == 403
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"Origin": config.public_app_url, "X-CSRF-Token": csrf}
    assert (
        client.post(
            "/api/v1/auth/invite/accept",
            json=payload,
            headers=headers | {"Origin": "https://evil.example.com"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/invite/accept", json=payload | {"role": "admin"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/auth/password/reset", json=payload, headers=headers).status_code == 400
    )
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"token": secret}, headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post("/api/v1/auth/invite/accept", json=payload, headers=headers).status_code == 200
    )
    assert (
        client.post("/api/v1/auth/invite/accept", json=payload, headers=headers).status_code == 400
    )
    assert client.get("/api/v1/admin/dashboard").status_code == 401  # No auto-login.
    with factory() as db:
        admin = db.scalar(select(User).where(User.role == "admin"))
        email, admin_id = admin.email, admin.id
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
        headers=headers,
    )
    assert login.status_code == 200 and login.json()["user"]["role"] == "admin"
    cookie = login.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "domain=" not in cookie
    assert client.get("/api/v1/admin/dashboard").status_code == 200
    authenticated_headers = {
        "Origin": config.public_app_url,
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    # A harmless authenticated mutation verifies CSRF without financial/provider writes.
    rotate = "/api/v1/auth/session/rotate"
    assert client.post(rotate, headers={"Origin": config.public_app_url}).status_code == 403
    assert client.post(rotate, headers=headers).status_code == 403  # Old pre-login CSRF.
    assert (
        client.post(
            rotate, headers=authenticated_headers | {"Origin": "https://untrusted.example.com"}
        ).status_code
        == 403
    )
    assert client.post(rotate, headers=authenticated_headers).status_code == 200
    assert client.get("/api/v1/me").status_code == 200
    reviewer = approval(config, actor=admin_id, purpose="reviewer")
    _, _, reviewer_secret = issue_committed(factory, config, reviewer)
    client.cookies.clear()
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers["X-CSRF-Token"] = csrf
    assert (
        client.post(
            "/api/v1/auth/invite/accept", json=payload | {"token": reviewer_secret}, headers=headers
        ).status_code
        == 200
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": reviewer.email, "password": payload["password"]},
        headers=headers,
    )
    assert login.status_code == 200 and client.cookies.get(COOKIE_NAME)
    assert client.get("/api/v1/admin/dashboard").status_code == 403
    client.close()
    app.state.redis.close()
    app.state.engine.dispose()


def test_cli_delivery_failure_rolls_back_and_uncertain_commit_never_regenerates(
    database, monkeypatch
):
    from pathlib import Path

    factory, config, engine = database
    proposal = approval(config)
    raw = proposal.model_dump_json().encode()
    monkeypatch.setattr(provision_staging, "Settings", lambda: config)
    monkeypatch.setattr(provision_staging, "build_engine", lambda _: engine)
    monkeypatch.setattr(Path, "read_bytes", lambda _: raw)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_staging",
            "issue",
            "--approval",
            "offline.json",
            "--expected-sha256",
            hashlib.sha256(raw).hexdigest(),
            "--token-output",
            "offline-token",
            "--execute",
        ],
    )

    def failed_delivery(*_):
        raise OSError("Offline disk failure")

    monkeypatch.setattr(provision_staging, "write_token", failed_delivery)
    with pytest.raises(OSError):
        provision_staging.main()
    with factory() as db:
        assert db.get(StagingInvite, proposal.operation_id) is None
        assert db.scalar(select(User).where(User.email == proposal.email)) is None
    artifacts = []
    monkeypatch.setattr(
        provision_staging, "write_token", lambda _, secret: artifacts.append(secret)
    )

    class UncertainSession(Session):
        def commit(self):
            super().commit()
            raise RuntimeError("Offline crash after durable commit")

    monkeypatch.setattr(provision_staging, "Session", UncertainSession)
    with pytest.raises(RuntimeError):
        provision_staging.main()
    assert len(artifacts) == 1
    with factory() as db:
        assert db.get(StagingInvite, proposal.operation_id).token_hash == digest(artifacts[0])
    monkeypatch.setattr(provision_staging, "Session", Session)
    with pytest.raises(ValueError, match="already issued"):
        provision_staging.main()
    assert len(artifacts) == 1


def test_forward_migration_matches_models_and_refuses_populated_downgrade(database):
    factory, config, engine = database
    with engine.begin() as connection:
        migration = Config("alembic.ini")
        migration.attributes["connection"] = connection
        command.check(migration)
    issue_committed(factory, config, approval(config))
    with pytest.raises(RuntimeError, match="Refusing to erase"), engine.begin() as connection:
        migration = Config("alembic.ini")
        migration.attributes["connection"] = connection
        command.downgrade(migration, "7b37ea061d28")
