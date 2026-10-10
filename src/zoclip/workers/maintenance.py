"""Local scheduler: durable dispatch, expired-worker recovery, private retention."""

import logging
import time

from redis import Redis
from sqlalchemy.orm import sessionmaker

from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.media.cleanup import cleanup
from zoclip.media.storage import LocalStorage
from zoclip.media.worker import dispatch, recover


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
                recover(factory)
                cleanup(factory, storage)
                dispatch(factory, redis)
            except Exception as exc:
                logging.error("maintenance_failed class=%s", type(exc).__name__)
            time.sleep(5)
    finally:
        redis.close()
        engine.dispose()


if __name__ == "__main__":
    main()
