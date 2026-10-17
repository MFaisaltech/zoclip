import logging
import os
from pathlib import Path
from uuid import uuid4

from redis import Redis
from rq import Queue, Worker

from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.ops.staging import verify_closed_runtime


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.private_staging:
        engine = build_engine(settings.database_url.get_secret_value())
        try:
            verify_closed_runtime(settings, engine)
        finally:
            engine.dispose()
    logging.basicConfig(level=logging.INFO)
    queue = os.environ.get("WORKER_QUEUE", "ai")
    if queue not in {"ai", "render"}:
        raise ValueError("Only ai and render queues supported")
    connection = Redis.from_url(settings.redis_url.get_secret_value())
    # Phase 3 registers ingestion on ai; render awaits Phase 5. Keep Redis private: RQ payloads
    # are trusted server messages, not input accepted from customers.
    prefix = os.environ.get("WORKER_NAME")
    worker = Worker(
        [Queue(queue, connection=connection)],
        connection=connection,
        name=prefix + "-" + uuid4().hex if prefix else None,
    )
    # RQ rejects reuse of a live registry name after SIGKILL. Each boot gets a new
    # name; the private health receipt identifies this process without deleting stale leases.
    Path("/tmp/zoclip-rq-worker-name").write_text(worker.name)
    worker.work()


if __name__ == "__main__":
    main()
