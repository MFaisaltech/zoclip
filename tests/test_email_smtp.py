import smtplib
import ssl

import pytest
from pydantic import ValidationError

from zoclip.auth.email import SMTPEmail, build_email
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


def config(**kwargs):
    values = dict(
        _env_file=None,
        database_url="postgresql+psycopg://offline/offline",
        public_app_url="https://app.example.com",
        email_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_username="transactional-user",
        smtp_password="offline-only-password",
        smtp_from="accounts@example.com",
        email_queue_key="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
    )
    return Settings(**(values | kwargs))


@pytest.mark.parametrize("tls,port", [("implicit", 465), ("starttls", 587)])
@pytest.mark.parametrize(
    "purpose,path", [("verify-email", "verify-email"), ("password-reset", "reset-password")]
)
def test_tls_email_has_private_link_and_no_secret_logs(
    monkeypatch, capsys, tls, port, purpose, path
):
    calls = []

    class Server:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.example.com"
            if tls == "implicit":
                assert kwargs["context"].check_hostname
                assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, *, context):
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append("tls")

        def login(self, username, password):
            assert tls == "implicit" or "tls" in calls
            calls.append("auth")

        def send_message(self, message, **kwargs):
            assert f"https://app.example.com/{path}#token=" + "T" * 43 in message.get_content()
            assert message["To"] == "customer@example.com"
            assert "offline-only-password" not in message.as_string()
            calls.append("sent")

    monkeypatch.setattr(smtplib, "SMTP_SSL" if tls == "implicit" else "SMTP", Server)
    sender = build_email(config(smtp_tls=tls, smtp_port=port))
    assert isinstance(sender, SMTPEmail)
    sender.send("customer@example.com", purpose, "T" * 43)
    assert calls.count("sent") == 1
    assert not capsys.readouterr().out


def test_starttls_refusal_never_authenticates_or_sends(monkeypatch):
    class Refused:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            pass

        def starttls(self, **kwargs):
            raise smtplib.SMTPNotSupportedError("sensitive diagnostic")

        def login(self, *args):
            pytest.fail("Plaintext credentials must not be sent")

        def send_message(self, *args, **kwargs):
            pytest.fail("No unencrypted mail")

    monkeypatch.setattr(smtplib, "SMTP", Refused)
    with pytest.raises(ApiError) as error:
        build_email(config(smtp_tls="starttls", smtp_port=587)).send(
            "a@example.com", "verify-email", "T" * 43
        )
    assert error.value.code == "email_delivery_failed"
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "override",
    [
        {"smtp_password": ""},
        {"smtp_from": None},
        {"smtp_host": "smtp.example.com:25"},
        {"smtp_tls": "starttls", "smtp_port": 465},
        {"smtp_host": "x\r\nmalicious"},
        {"public_app_url": "http://app.example.com"},
        {"email_queue_key": ""},
        {"email_queue_key": "invalid"},
    ],
)
def test_smtp_config_fails_closed(override):
    with pytest.raises(ValidationError):
        config(**override)


def test_smtp_signup_verify_reset_and_repeat_login(client, app, monkeypatch):
    import re

    from test_auth import PASSWORD, csrf, login

    messages = []

    class MailServer:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, *args):
            pass

        def send_message(self, message, **kwargs):
            messages.append(message)

    monkeypatch.setattr(smtplib, "SMTP_SSL", MailServer)
    app.state.email_sender = build_email(config())
    app.state.settings = config().model_copy(
        update={
            "database_url": app.state.settings.database_url,
            "public_app_url": app.state.settings.public_app_url,
            "app_env": "test",
            "cookie_secure": False,
            "auth_rate_limit": 100,
        }
    )
    headers = csrf(client)
    result = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": "new@example.com", "password": PASSWORD},
    )
    assert result.status_code == 202 and len(messages) == 0
    from zoclip.auth.mail_queue import deliver_one

    assert deliver_one(app.state.session_factory, app.state.settings)
    assert len(messages) == 1
    raw = re.search(r"#token=([A-Za-z0-9_-]+)", messages[-1].get_content()).group(1)
    assert (
        client.post("/api/v1/auth/verify-email", headers=headers, json={"token": raw}).status_code
        == 200
    )
    headers = login(client, headers, "new@example.com")
    assert client.get("/api/v1/me").json()["email"] == "new@example.com"
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    headers = csrf(client)
    assert (
        client.post(
            "/api/v1/auth/password/forgot", headers=headers, json={"email": "new@example.com"}
        ).status_code
        == 202
    )
    assert deliver_one(app.state.session_factory, app.state.settings)
    raw = re.search(r"#token=([A-Za-z0-9_-]+)", messages[-1].get_content()).group(1)
    replacement = "another sufficiently long password"
    assert (
        client.post(
            "/api/v1/auth/password/reset",
            headers=headers,
            json={"token": raw, "password": replacement},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=csrf(client),
            json={"email": "new@example.com", "password": replacement},
        ).status_code
        == 200
    )
    assert len(messages) == 2


def test_smtp_failure_does_not_reveal_account_eligibility(client, app):
    from sqlalchemy import select
    from test_auth import csrf, register

    from zoclip.auth.models import AuditLog

    register(client, app)

    class Failed:
        def ensure_available(self):
            pass

        def send(self, *args):
            raise ApiError(503, "email_delivery_failed", "Hidden transport details")

    app.state.email_sender = Failed()
    headers = csrf(client)
    known = client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "alice@example.com"}
    )
    unknown = client.post(
        "/api/v1/auth/password/forgot", headers=headers, json={"email": "unknown@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    with app.state.session_factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.email_delivery_failed"))
