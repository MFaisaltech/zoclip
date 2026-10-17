"""Offline staging fences: no database, Redis, containers or provider connections."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from zoclip.auth.routes import register
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.credits.routes import policy
from zoclip.main import create_app
from zoclip.ops.staging import verify_closed_runtime

BASE = {
    "_env_file": None,
    "app_env": "production",
    "private_staging": True,
    "staging_site_domain": "example.com",
    "database_url": "postgresql+psycopg://configured:offline-only-password@db/test",
    "public_app_url": "https://app.staging.example.com",
    "api_public_url": "https://api.staging.example.com:8443",
    "allowed_hosts": ["api.staging.example.com"],
}


@pytest.mark.parametrize(
    "override",
    [
        {"app_env": "test"},
        {"registration_enabled": True},
        {"email_mode": "development"},
        {"enable_live_payments": True},
        {"enable_trial_credits": True},
        {"payment_provider": "jazzcash"},
        {"ai_enabled": True},
        {"deepgram_api_key": "offline-only-key-must-be-absent"},
        {"gemini_api_key": "offline-only-key-must-be-absent"},
        {"media_allowed_import_hosts": ["media.example.com"]},
        {"staging_site_domain": "vercel.app"},
        {"staging_site_domain": ""},
        {"public_app_url": "https://customer.vercel.app"},
        {"api_public_url": "https://evil-example.com"},
        {"allowed_hosts": ["*.example.com"]},
        {"staging_site_domain": "-invalid.example.com"},
        {"public_app_url": "https://APP.staging.example.com"},
        {"api_public_url": "https://api.staging.example.com:443"},
        {
            "api_public_url": "https://app.staging.example.com:8443",
            "allowed_hosts": ["app.staging.example.com"],
        },
        {
            "api_public_url": "https://-invalid.staging.example.com:8443",
            "allowed_hosts": ["-invalid.staging.example.com"],
        },
        {"cookie_secure": False},
    ],
)
def test_private_config_rejects_unsafe_combinations(override):
    with pytest.raises((ValidationError, ValueError)):
        Settings(**(BASE | override))


@pytest.mark.parametrize("breaker,allowed", [(True, True), (False, False), (None, False)])
def test_breaker_startup_check_is_read_only_and_fails_closed(breaker, allowed):
    statements = []
    connection = SimpleNamespace(
        execute=lambda sql: statements.append(str(sql)),
        scalar=lambda sql: statements.append(str(sql)) or breaker,
    )

    @contextmanager
    def connect():
        yield connection

    engine = SimpleNamespace(connect=connect)
    if allowed:
        verify_closed_runtime(Settings(**BASE), engine)
    else:
        with pytest.raises(RuntimeError, match="breaker=true"):
            verify_closed_runtime(Settings(**BASE), engine)
    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SELECT breaker FROM system_limits WHERE id=1",
    ]


def request_for(settings):
    return Request(
        {"type": "http", "app": SimpleNamespace(state=SimpleNamespace(settings=settings))}
    )


def test_closed_policy_cannot_be_opened_even_by_admin_handler():
    db = Mock()
    with pytest.raises(ApiError) as error:
        policy(
            SimpleNamespace(breaker=False),
            "offline-operation",
            request_for(Settings(**BASE)),
            db,
            Mock(),
            Mock(),
        )
    assert error.value.code == "staging_spending_disabled"
    assert not db.mock_calls


def test_public_registration_denied_before_hashing_or_database_work():
    db = Mock()
    with pytest.raises(ApiError) as error:
        register(Mock(), request_for(Settings(**BASE)), db, Mock())
    assert error.value.code == "registration_disabled"
    assert not db.mock_calls


def test_cors_exact_origin_and_admin_unauthenticated_denial():
    # No lifespan entered: no startup database check, and absent cookies require no DB query.
    app = create_app(Settings(**BASE))
    client = TestClient(app, base_url=BASE["api_public_url"])
    headers = {
        "Origin": BASE["public_app_url"],
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-Token,Idempotency-Key",
    }
    good = client.options("/api/v1/admin/limits/versions", headers=headers)
    assert good.status_code == 200
    assert good.headers["access-control-allow-origin"] == BASE["public_app_url"]
    assert good.headers["access-control-allow-credentials"] == "true"
    bad = client.options(
        "/api/v1/admin/limits/versions",
        headers=headers | {"Origin": "https://untrusted.example.com"},
    )
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    assert client.get("/api/v1/admin/dashboard").status_code == 401
    assert client.get("/openapi.json").status_code == 404
    client.close()
    app.state.redis.close()
    app.state.engine.dispose()
