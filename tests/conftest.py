import os
from collections.abc import Generator
from pathlib import Path

import fakeredis
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.main import create_app


@pytest.fixture
def bootstrap_revision():
    return "head"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL required; no SQLite substitute")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Use a disposable PostgreSQL database ending in _test")
    return url


@pytest.fixture(scope="session")
def migrated_database(database_url: str):
    # Explicit disposable target only. Never run downgrade against deployment DB.
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
    if original is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original
    yield database_url


@pytest.fixture
def app(migrated_database: str, tmp_path: Path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated_database,
        cookie_secure=False,
        email_mode="development",
        dev_mailbox_dir=str(tmp_path / "mailbox"),
        auth_rate_limit=100,
        media_root=str(tmp_path / "media"),
        media_part_bytes=65536,
    )
    application = create_app(settings)
    engine = build_engine(migrated_database)
    connection = engine.connect()
    transaction = connection.begin()
    application.state.session_factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    redis_url = os.environ.get("TEST_REDIS_URL")
    if redis_url:
        if not redis_url.endswith("/15"):
            pytest.fail("TEST_REDIS_URL must target disposable database 15")
        application.state.redis = Redis.from_url(redis_url, socket_timeout=3)
        application.state.redis.flushdb()
    else:
        application.state.redis = fakeredis.FakeRedis()
    yield application
    transaction.rollback()
    if redis_url:
        application.state.redis.flushdb()
    application.state.redis.close()
    connection.close()
    engine.dispose()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app, base_url="http://localhost:8000") as value:
        yield value
