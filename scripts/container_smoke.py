"""Run inside the API container of an isolated development Compose test project.

Uses actual DB/Redis and the running ai/render workers; no external providers.
Never run against production queues. Any failed assertion exits nonzero.
"""

import operator
import time
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from redis import Redis
from rq import Queue
from sqlalchemy import text
from sqlalchemy.orm import Session

from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.credits.service import adjust, lock_wallet, reconcile


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.app_env != "development":
        raise RuntimeError("Smoke jobs are permitted only in isolated development projects")
    request = urllib.request.Request(
        "http://localhost:8000/health/ready",
        headers={"Host": urlsplit(settings.api_public_url).netloc},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
    print("API readiness: PASS")

    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            actual = MigrationContext.configure(connection).get_current_heads()
            expected = tuple(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
            assert actual == expected, "Database migration revision differs from code"
            print("PostgreSQL connectivity/migration head: PASS")
        # Exercise financial code under Linux, then roll back every smoke row.
        # The full concurrency suite uses committed independent transactions.
        with Session(engine) as db:
            actor = User(
                email=f"smoke-admin-{uuid4()}@example.invalid", verified=True, role="admin"
            )
            owner = User(email=f"smoke-owner-{uuid4()}@example.invalid", verified=True)
            db.add_all([actor, owner])
            db.flush()
            first = adjust(db, owner.id, 2, "smoke", actor.id, "Isolated smoke grant", grant=True)
            again = adjust(db, owner.id, 2, "smoke", actor.id, "Isolated smoke grant", grant=True)
            assert first.id == again.id
            wallet = lock_wallet(db, owner.id)
            assert (wallet.available, wallet.reserved) == (2, 0)
            reconcile(db, wallet)
            db.rollback()
            assert db.get(User, owner.id) is None
            print("PostgreSQL financial grant/idempotency/reconcile/rollback: PASS")
    finally:
        engine.dispose()

    redis = Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=5)
    try:
        assert redis.ping()
        print("Redis PING: PASS")
        for name in ("ai", "render"):
            queue = Queue(name, connection=redis)
            job = queue.enqueue(operator.add, 20, 22, result_ttl=60, job_timeout=30)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    job.refresh()
                    if job.is_finished or job.is_failed:
                        break
                    time.sleep(0.5)
                assert job.is_finished, f"{name} worker did not complete the smoke job"
                assert job.return_value(refresh=True) == 42
                print(f"RQ {name} worker result: PASS (42)")
            finally:
                job.delete()
    finally:
        redis.close()


if __name__ == "__main__":
    main()
