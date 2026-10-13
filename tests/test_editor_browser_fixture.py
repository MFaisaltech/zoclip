"""Synthetic browser admission is inaccessible outside its explicit disposable scope."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from scripts import editor_browser_api


@pytest.mark.parametrize(
    "override",
    [
        {"app_env": "production"},
        {"ai_enabled": True},
        {"database_url": SecretStr("postgresql+psycopg://unused:unused@127.0.0.1:55438/real_data")},
        {"media_root": "var/real_media"},
    ],
)
def test_synthetic_browser_capacity_refuses_nonfixture_configuration(monkeypatch, override):
    root = Path(editor_browser_api.__file__).resolve().parents[1]
    settings = SimpleNamespace(
        **{
            "app_env": "development",
            "ai_enabled": False,
            "database_url": SecretStr(
                "postgresql+psycopg://unused:unused@127.0.0.1:55438/zoclip_phase8_browser_test"
            ),
            "media_root": str(root / "var/phase8-auth/synthetic/media"),
            **override,
        }
    )
    monkeypatch.setattr(editor_browser_api, "Settings", lambda: settings)
    monkeypatch.setattr(
        editor_browser_api,
        "create_app",
        lambda settings: pytest.fail("Must reject before app creation"),
    )
    with pytest.raises(RuntimeError, match="Disposable disabled-provider"):
        editor_browser_api.create_test_app()
