"""Explicit disposable Linux browser harness: real local inference, no provider IO.

The YouTube transport returns the supplied authorized local fixture. The separate
youtube_worker_smoke verifies real WARP/PO-token downloads. Never use on staging.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import UUID

import uvicorn
from alembic.config import Config
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.ai import worker as ai
from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.core.security import hash_password
from zoclip.credits import service as money
from zoclip.credits.schemas import PolicyInput
from zoclip.main import create_app
from zoclip.media import worker
from zoclip.media.storage import LocalStorage

ROOT = Path("/app")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "api", "worker"])
    parser.add_argument("--allow-disposable-local", action="store_true")
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state_path = args.state.resolve()
    if not args.allow_disposable_local or not state_path.is_relative_to(ROOT / "var/phase8-auth"):
        parser.error("Disposable state path and explicit opt-in required")
    state = json.loads(state_path.read_text())
    url = make_url(state["database_url"])
    if (url.host, url.port, url.database) != ("127.0.0.1", 55438, "zoclip_generation_browser_test"):
        parser.error("Refusing any non-disposable database")
    engine = build_engine(state["database_url"])
    factory = sessionmaker(engine, expire_on_commit=False)
    manifest = state_path.with_name("generation-fixture.json")
    sys.path.insert(0, str(ROOT / "tests"))
    if args.mode == "seed":
        if manifest.exists():
            parser.error("Preserving existing fixture; seed is single-use")
        with engine.connect() as db:
            if db.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")):
                parser.error("Seed requires a newly initialized empty database")
        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        from test_ai import configure
        from test_credits import seed

        users = seed(factory, balance=20)
        base = Settings(_env_file=None, database_url=state["database_url"])
        configured = configure(factory, users, base)
        settings = Settings(
            _env_file=None,
            **(
                configured.model_dump()
                | {
                    "app_env": "development",
                    "cookie_secure": False,
                    "database_url": state["database_url"],
                    "redis_url": "redis://127.0.0.1:6379/0",
                    "media_root": str(state_path.parent / "media"),
                    "media_part_bytes": 65536,
                    "dev_mailbox_dir": state["mailbox"],
                    "email_mode": "development",
                    "analysis_provider": "local",
                    "transcription_provider": "whisper",
                    "gemini_api_key": "",
                    "deepgram_api_key": "",
                    "gemini_model": "",
                    "api_public_url": state["api_origin"],
                    "auth_rate_limit": 100,
                    "whisper_parallelism": 1,
                    "whisper_cpu_threads": 2,
                }
            ),
        )
        password = "Disposable local generation fixture 83!"
        with factory() as db:
            user = db.get(User, users["alice"])
            user.password_hash = hash_password(password)
            limits = users["ai_limits"].model_copy(
                update={"render_cpu_seconds_per_output": 520, "storage_gb_days_per_output": 2}
            )
            money.configure_policy(
                db,
                PolicyInput(limits=limits, reason="Local browser fixture"),
                "browser-render",
                users["admin"],
            )
            email = user.email
            db.commit()
        manifest.write_text(
            json.dumps(
                {
                    "email": email,
                    "password": password,
                    "settings": settings.model_dump(
                        mode="json", exclude={"database_url", "redis_url"}
                    ),
                }
            )
        )
        manifest.chmod(0o600)
        print("Disposable local generation fixture initialized; no paid credentials", flush=True)
        return
    fixture = json.loads(manifest.read_text())
    settings = Settings(
        _env_file=None,
        **(
            fixture["settings"]
            | {"database_url": state["database_url"], "redis_url": "redis://127.0.0.1:6379/0"}
        ),
    )
    if args.mode == "api":
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8017, access_log=False)
        return

    def forbidden(*args, **kwargs):
        raise RuntimeError("Paid provider IO forbidden in disposable local harness")

    ai.HTTPProviders.transcribe = forbidden
    ai.HTTPProviders.analyze = forbidden

    def downloaded(url, dest, settings, progress):
        if url != "https://www.youtube.com/watch?v=aqz-KE-bpKQ":
            raise ValueError("Unknown authorized fixture URL")
        data = Path("/authorized-media.mp4").read_bytes()
        if len(data) > settings.media_max_bytes:
            raise ValueError("Fixture exceeds admitted limit")
        dest.write_bytes(data)
        return len(data)

    worker.download_youtube = downloaded
    storage = LocalStorage(settings.media_root)
    worker.execute = lambda job_id, generation: worker.run_job(
        UUID(job_id), generation, factory, settings, storage
    )
    with Redis.from_url(settings.redis_url.get_secret_value()) as redis:
        while True:
            worker.dispatch(factory, redis)
            SimpleWorker(
                [Queue("ai", connection=redis), Queue("render", connection=redis)], connection=redis
            ).work(burst=True, logging_level="ERROR")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
