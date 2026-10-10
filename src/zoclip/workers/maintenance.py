"""Local scheduler: durable dispatch, expired-worker recovery, private retention."""

import logging
import time
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import sessionmaker

from zoclip.ai.worker import resume_waiting
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.media.cleanup import cleanup
from zoclip.media.storage import LocalStorage
from zoclip.media.worker import dispatch, recover
from zoclip.ops.privacy import cleanup_auth


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=5, socket_connect_timeout=5
    )
    storage = LocalStorage(settings.media_root)
    try:
        while True:
            try:
                recover(factory, storage)
                cleanup(factory, storage)
                resume_waiting(factory, settings)
                dispatch(factory, redis)
                with factory() as db:
                    cleanup_auth(db)
                    db.commit()
                Path("/tmp/zoclip-maintenance-heartbeat").touch()
            except Exception as exc:
                logging.error("maintenance_failed class=%s", type(exc).__name__)
            time.sleep(5)
    finally:
        redis.close()
        engine.dispose()


if __name__ == "__main__":
    main()
