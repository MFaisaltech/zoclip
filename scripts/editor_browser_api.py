"""Explicit disposable M4 API fixture with synthetic capacity, never a deploy entrypoint."""

from pathlib import Path

from sqlalchemy.engine import make_url

from zoclip.core.config import Settings
from zoclip.main import create_app
from zoclip.media.storage import LocalStorage


def create_test_app():
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    root = Path(__file__).resolve().parents[1] / "var/phase8-auth"
    if (
        settings.app_env != "development"
        or settings.ai_enabled
        or (url.host, url.port, url.database) != ("127.0.0.1", 55438, "zoclip_phase8_browser_test")
        or not Path(settings.media_root).resolve().is_relative_to(root)
    ):
        raise RuntimeError("Disposable disabled-provider browser harness only")
    actual = LocalStorage.free_bytes

    def synthetic(self):
        if actual(self) < 1024**3:
            raise RuntimeError("Fixture disk must retain at least 1 GiB actual space")
        return 1024**4

    LocalStorage.free_bytes = synthetic
    return create_app(settings)
