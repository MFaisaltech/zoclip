import logging
import os

from redis import Redis
from rq import Queue, Worker

from zoclip.core.config import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(level=logging.INFO)
    queue = os.environ.get("WORKER_QUEUE", "ai")
    if queue not in {"ai", "render"}:
        raise ValueError("Only ai and render queues supported")
    connection = Redis.from_url(settings.redis_url.get_secret_value())
    # Phase 3 registers ingestion on ai; render awaits Phase 5. Keep Redis private: RQ payloads
    # are trusted server messages, not input accepted from customers.
    Worker([Queue(queue, connection=connection)], connection=connection).work()


if __name__ == "__main__":
    main()
