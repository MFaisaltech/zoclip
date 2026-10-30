"""Read-only startup fence for private staging; never changes financial controls."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from zoclip.core.config import Settings


def verify_closed_runtime(settings: Settings, engine: Engine) -> None:
    if not settings.private_staging:
        return
    if settings.staging_generation_enabled:
        # Configuration already restricts this mode to one local-only staging account.
        # Normal reservation/budget checks still enforce the financial breaker.
        return
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        if connection.scalar(text("SELECT breaker FROM system_limits WHERE id=1")) is not True:
            raise RuntimeError("Private staging requires an existing breaker=true; no auto-repair")
