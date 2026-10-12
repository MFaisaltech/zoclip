import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from zoclip.auth.models import (
    AuditLog,
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    User,
)
from zoclip.core.db import build_engine, utcnow
from zoclip.core.security import COOKIE_NAME, digest

PASSWORD = "a sufficiently long password"
ORIGIN = "http://localhost:3000"
pytestmark = pytest.mark.integration


def csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200, response.text
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def mailbox(app, purpose, email="alice@example.com"):
    paths = sorted(
        Path(app.state.settings.dev_mailbox_dir).glob("*.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    entries = [json.loads(path.read_text()) for path in paths]
    return [
        entry["token"]
        for entry in entries
        if entry["purpose"] == purpose and entry["recipient"] == email
    ][-1]


def register(client, app, email="alice@example.com", verify=True):
    headers = csrf(client)
    result = client.post(
        "/api/v1/auth/register", headers=headers, json={"email": email, "password": PASSWORD}
    )
    assert result.status_code == 202, result.text
    if verify:
        raw = mailbox(app, "verify-email", email.lower())
        result = client.post("/api/v1/auth/verify-email", headers=headers, json={"token": raw})
        assert result.status_code == 200, result.text
    return headers


def login(client, headers, email="alice@example.com"):
    result = client.post(
        "/api/v1/auth/login", headers=headers, json={"email": email, "password": PASSWORD}
    )
    assert result.status_code == 200, result.text
    return {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}


def test_register_verify_login_logout_rotation_and_hashes(client, app):
    headers = register(client, app, email="ALICE@example.com")
    anonymous = client.cookies.get(COOKIE_NAME)
    headers = login(client, headers)
    authenticated = client.cookies.get(COOKIE_NAME)
    assert authenticated != anonymous
    response = client.get("/api/v1/me")
    assert response.json()["email"] == "alice@example.com"
    assert "password" not in response.text and "token" not in response.text
    with app.state.session_factory() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != PASSWORD
        entry = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == digest(authenticated))
        )
        assert entry and entry.csrf_hash != headers["X-CSRF-Token"]
        verified = db.scalar(select(EmailVerificationToken))
        assert verified.token_hash != mailbox(app, "verify-email") and verified.consumed_at
    rotated = client.post("/api/v1/auth/session/rotate", headers=headers)
    assert rotated.status_code == 200
    client.cookies.set(COOKIE_NAME, authenticated)
    assert client.get("/api/v1/me").status_code == 401
    client.cookies.clear()
    headers = login(client, csrf(client))
    raw = client.cookies.get(COOKIE_NAME)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    client.cookies.set(COOKIE_NAME, raw)
    assert client.get("/api/v1/me").status_code == 401


def test_unverified_wrong_password_unknown_and_duplicate(client, app):
    headers = register(client, app, verify=False)
    for email, password in [
        ("alice@example.com", PASSWORD),
        ("nobody@example.com", PASSWORD),
        ("alice@example.com", "an incorrect long password"),
    ]:
        response = client.post(
            "/api/v1/auth/login", headers=headers, json={"email": email, "password": password}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"
    duplicate = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert duplicate.status_code == 202
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(User)))) == 1


@pytest.mark.parametrize("variant", ["missing", "bad-token", "bad-origin", "no-origin"])
def test_csrf_rejects_mutations(client, variant):
    headers = csrf(client)
    if variant == "missing":
        headers.pop("X-CSRF-Token")
    elif variant == "bad-token":
        headers["X-CSRF-Token"] = "forged"
    elif variant == "bad-origin":
        headers["Origin"] = "https://attacker.example"
    else:
        headers.pop("Origin")
    response = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert response.status_code == 403


def test_forged_expired_revoked_and_disabled_sessions(client, app):
    client.cookies.set(COOKIE_NAME, "forged")
    assert client.get("/api/v1/me").status_code == 401
    client.cookies.clear()
    headers = login(client, register(client, app))
    raw = client.cookies.get(COOKIE_NAME)
    with app.state.session_factory() as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == digest(raw))
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        db.commit()
    assert client.get("/api/v1/me").status_code == 401
    client.cookies.clear()
    login(client, csrf(client))
    with app.state.session_factory() as db:
        db.execute(update(User).values(status="disabled"))
        db.commit()
    assert client.get("/api/v1/me").status_code == 401
    assert client.post("/api/v1/auth/session/rotate", headers=headers).status_code in {401, 403}


def test_verification_token_expiry_and_replay(client, app):
    headers = register(client, app, verify=False)
    raw = mailbox(app, "verify-email")
    with app.state.session_factory() as db:
        db.execute(
            update(EmailVerificationToken).values(expires_at=utcnow() - timedelta(seconds=1))
        )
        db.commit()
    assert (
        client.post("/api/v1/auth/verify-email", headers=headers, json={"token": raw}).status_code
        == 400
    )
    headers = register(client, app)
    raw = mailbox(app, "verify-email")
    assert (
        client.post("/api/v1/auth/verify-email", headers=headers, json={"token": raw}).status_code
        == 400
    )


def test_password_reset_single_use_and_revokes_all_sessions(client, app):
    headers = login(client, register(client, app))
    authenticated = client.cookies.get(COOKIE_NAME)
    response = client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "alice@example.com"}
    )
    unknown = client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "unknown@example.com"}
    )
    assert response.status_code == unknown.status_code == 202
    assert response.json() == unknown.json()
    raw = mailbox(app, "password-reset")
    with app.state.session_factory() as db:
        assert db.scalar(select(PasswordResetToken)).token_hash == digest(raw)
    # Reset through a different anonymous browser; all authenticated sessions are revoked.
    with TestClient(app, base_url="http://localhost:8000") as other:
        other_headers = csrf(other)
        body = {"token": raw, "password": "a brand new long password"}
        assert (
            other.post("/api/v1/auth/password/reset", headers=other_headers, json=body).status_code
            == 200
        )
        assert (
            other.post("/api/v1/auth/password/reset", headers=other_headers, json=body).status_code
            == 400
        )
    assert client.cookies.get(COOKIE_NAME) == authenticated
    assert client.get("/api/v1/me").status_code == 401
    client.cookies.clear()
    headers = csrf(client)
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"email": "alice@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"email": "alice@example.com", "password": "a brand new long password"},
        ).status_code
        == 200
    )


def test_expired_and_superseded_reset_tokens(client, app):
    headers = register(client, app)
    client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "alice@example.com"}
    )
    old = mailbox(app, "password-reset")
    client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "alice@example.com"}
    )
    with app.state.session_factory() as db:
        db.execute(update(PasswordResetToken).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    for raw in (old, mailbox(app, "password-reset"), "x" * 43):
        assert (
            client.post(
                "/api/v1/auth/password/reset",
                headers=headers,
                json={"token": raw, "password": PASSWORD},
            ).status_code
            == 400
        )


def test_alice_bob_resource_isolation_and_staff_permissions(client, app):
    login(client, register(client, app))
    alice = client.get("/api/v1/me").json()["id"]
    with app.state.session_factory() as db:
        alice_session = db.scalar(select(AuthSession).where(AuthSession.user_id == UUID(alice)))
        alice_session_id = str(alice_session.id)
    with TestClient(app, base_url="http://localhost:8000") as bob:
        login(bob, register(bob, app, "bob@example.com"), "bob@example.com")
        assert bob.get("/api/v1/me").json()["id"] != alice
        assert bob.get(f"/api/v1/me/sessions/{alice_session_id}").status_code == 404
    assert client.get(f"/api/v1/me/sessions/{alice_session_id}").status_code == 200
    assert client.get("/api/v1/admin/audit-logs").status_code == 403
    with app.state.session_factory() as db:
        db.execute(update(User).where(User.id == UUID(alice)).values(role="admin"))
        db.commit()
    result = client.get("/api/v1/admin/audit-logs?limit=1")
    assert result.status_code == 200 and result.json()["next_cursor"]
    with app.state.session_factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.audit_read"))


def test_cannot_self_assign_role_and_validation_does_not_echo_secrets(client, app):
    headers = csrf(client)
    result = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": "alice@example.com", "password": PASSWORD, "role": "admin"},
    )
    assert result.status_code == 422
    assert PASSWORD not in result.text and "alice@example.com" not in result.text


def test_rate_limit_and_redis_failure_fail_closed(client, app, monkeypatch):
    headers = csrf(client)
    app.state.settings.auth_rate_limit = 2
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"email": "unknown@example.com", "password": PASSWORD},
            ).status_code
            == 401
        )
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "unknown@example.com", "password": PASSWORD},
    )
    assert response.status_code == 429 and response.headers["Retry-After"]
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()

    def unavailable(*args, **kwargs):
        raise RedisConnectionError("sensitive internal address")

    monkeypatch.setattr(app.state.redis, "eval", unavailable)
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "unknown@example.com", "password": PASSWORD},
    )
    assert response.status_code == 503 and "sensitive" not in response.text


def test_unconfigured_email_fails_honestly(client, app):
    from zoclip.auth.email import DisabledEmail

    app.state.email_sender = DisabledEmail()
    headers = csrf(client)
    response = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert response.status_code == 503 and response.json()["code"] == "email_unconfigured"
    with app.state.session_factory() as db:
        assert db.scalar(select(User)) is None


def test_security_headers_cors_body_limit_health_and_logging(client, caplog):
    response = client.get("/health/live", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/health/ready").status_code == 200
    assert (
        "access-control-allow-origin"
        not in client.get("/health/live", headers={"Origin": "https://evil.example"}).headers
    )
    assert client.get("/health/live", headers={"Host": "evil.example"}).status_code == 400
    response = client.post("/api/v1/auth/register", content=b"x" * 17000)
    assert response.status_code == 413
    with caplog.at_level("INFO", logger="zoclip.requests"):
        client.get("/api/v1/auth/google/callback?code=DO_NOT_LOG_ME&state=SECRET_STATE")
    assert "DO_NOT_LOG_ME" not in " ".join(
        record.message for record in caplog.records if record.name == "zoclip.requests"
    )


def test_audit_logs_are_immutable(app):
    with app.state.session_factory() as db:
        db.add(AuditLog(action="test", request_id="test"))
        db.commit()
    with app.state.session_factory() as db, pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM admin_audit_logs"))


def test_concurrent_verification_consumes_once(migrated_database):
    # Separate real connections/transactions; not a shared transactional test fixture.
    from uuid import uuid4

    from sqlalchemy.orm import Session

    from zoclip.auth.service import consume_email_token
    from zoclip.core.errors import ApiError

    engine = build_engine(migrated_database)
    raw = str(uuid4()) + str(uuid4())
    with Session(engine) as db:
        user = User(email=f"race-{uuid4()}@example.com")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(
            EmailVerificationToken(
                user_id=user.id, token_hash=digest(raw), expires_at=utcnow() + timedelta(minutes=5)
            )
        )
        db.commit()

    def consume():
        with Session(engine) as db:
            try:
                consume_email_token(db, raw, EmailVerificationToken)
                db.commit()
                return "consumed"
            except ApiError:
                db.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))
    assert sorted(results) == ["consumed", "rejected"]
    with Session(engine) as db:
        db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
    engine.dispose()


def test_secure_cookie_flags(client, app):
    app.state.settings.cookie_secure = True
    response = client.get("/api/v1/auth/csrf")
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "domain=" not in cookie


def test_database_failure_returns_safe_problem(client, app, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def unavailable():
        raise OperationalError("private SQL", {}, Exception("secret database password"))

    monkeypatch.setattr(app.state, "session_factory", unavailable)
    response = client.get("/api/v1/me")
    assert response.status_code == 503
    assert "secret" not in response.text and "private SQL" not in response.text
