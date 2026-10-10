import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from zoclip.core.config import Settings
from zoclip.main import create_app

BASE = {"_env_file": None, "database_url": "postgresql+psycopg://test@localhost/test"}


@pytest.mark.parametrize(
    "override",
    [
        {"database_url": "sqlite:///test.db"},
        {"google_client_id": "partial"},
        {"allowed_hosts": ["*"]},
        {"public_app_url": "https://app.example/path"},
        {"enable_live_payments": True},
        {"enable_trial_credits": True},
        {"app_env": "production", "cookie_secure": False},
        {"app_env": "production", "email_mode": "development"},
    ],
)
def test_reject_unsafe_config(override):
    with pytest.raises((ValidationError, ValueError)):
        Settings(**(BASE | override))


def test_production_cookies_docs_and_disabled_services():
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://configured:unit-test-only-password@db/test",
        public_app_url="https://app.example.com",
        api_public_url="https://api.example.com",
        allowed_hosts=["api.example.com"],
    )
    with TestClient(create_app(settings), base_url="https://api.example.com") as client:
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health/live").headers["strict-transport-security"]
        result = client.get("/api/v1/auth/google/start")
        assert result.status_code == 503 and result.json()["code"] == "google_unconfigured"


def test_openapi_is_valid_and_matches_export():
    app = create_app(Settings(**BASE))
    schema = app.openapi()
    validate(schema)
    assert schema == json.loads(Path("docs/openapi.json").read_text())
    assert "/api/v1/me" in schema["paths"]
    assert "/api/v1/me/credits" in schema["paths"]
    assert "/api/v1/billing/orders" not in schema["paths"]
    assert "/api/v1/uploads" in schema["paths"]
