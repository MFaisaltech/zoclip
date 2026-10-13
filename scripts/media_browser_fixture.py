"""Opt-in M3 fixture/worker. ONLY the disposable auth_dev database; never live IO."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.core.security import hash_password
from zoclip.media import worker
from zoclip.media.storage import LocalStorage

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-disposable-local", action="store_true")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--ffmpeg-bin", type=Path, required=True)
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    state_path = args.state.resolve()
    if (
        not args.allow_disposable_local
        or not state_path.is_relative_to(ROOT / "var/phase8-auth")
        or state_path.name != "state.json"
    ):
        parser.error("Explicit disposable state/opt-in required")
    state = json.loads(state_path.read_text())
    url = make_url(state["database_url"])
    if (url.drivername, url.host, url.port, url.database) != (
        "postgresql+psycopg",
        "127.0.0.1",
        55438,
        "zoclip_phase8_browser_test",
    ):
        parser.error("Refusing any non-disposable database")
    if not all((args.ffmpeg_bin / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")):
        parser.error("Explicit local FFmpeg/ffprobe binaries required")
    sys.path.insert(0, str(ROOT / "tests"))
    from test_ai import Simulator, configure
    from test_credits import seed

    from zoclip.ai import worker as ai
    from zoclip.auth.models import User
    from zoclip.credits import service as credits
    from zoclip.media.cleanup import cleanup

    engine = build_engine(state["database_url"])
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=state["database_url"],
        media_root=str(state_path.parent / "media"),
        media_part_bytes=65536,
        media_allowed_import_hosts=["media.example.com"],
        ffmpeg_binary=str(args.ffmpeg_bin / "ffmpeg.exe"),
        ffprobe_binary=str(args.ffmpeg_bin / "ffprobe.exe"),
    )
    manifest = state_path.with_name("media-fixture.json")
    try:
        if args.seed:
            if manifest.exists():
                parser.error("Fixtures already exist; preserving existing data")
            users = seed(factory)
            settings = configure(factory, users, settings)
            settings.ffmpeg_binary = str(args.ffmpeg_bin / "ffmpeg.exe")
            password = "Disposable media fixture password 83!"
            result = {"password": password, "users": {}}
            with factory() as db:
                for name in ("alice", "bob"):
                    user = db.get(User, users[name])
                    user.password_hash = hash_password(password)
                    result["users"][name] = {"id": str(user.id), "email": user.email}
                credits.adjust(
                    db,
                    users["bob"],
                    -5,
                    "m3-empty-wallet",
                    users["admin"],
                    "Explicit empty wallet fixture",
                )
                db.commit()
            # Only fictional provider credentials; the DB secret stays in state.json.
            result["settings"] = settings.model_dump(
                mode="json", exclude={"database_url", "deepgram_api_key", "gemini_api_key"}
            )
            manifest.write_text(json.dumps(result), encoding="utf-8")
            manifest.chmod(0o600)
            print("Synthetic M3 accounts/rates saved in disposable private manifest.")
            return
        fixture = json.loads(manifest.read_text())
        settings = Settings(
            _env_file=None,
            **{
                **fixture["settings"],
                "database_url": state["database_url"],
                "redis_url": state["test_redis_url"].rsplit("/", 1)[0] + "/0",
                "deepgram_api_key": "unused",
                "gemini_api_key": "unused",
            },
        )
        ai.HTTPProviders = lambda settings: Simulator()  # Existing test-only adapter, no vendor IO.
        storage = LocalStorage(settings.media_root)

        def download(url, hosts, output, max_bytes, **kwargs):
            # API initiation still runs the unchanged HTTPS/allowlist policy. This fixture
            # replaces transport ONLY; production SSRF/TLS is covered by existing tests.
            if url not in {
                "https://media.example.com/source.mp4",
                "https://media.example.com/invalid.mp4",
            }:
                raise ValueError("Unknown synthetic URL")
            data = (
                (ROOT / "tests/fixtures/source.mp4").read_bytes()
                if url.endswith("/source.mp4")
                else b"invalid synthetic media"
            )
            if len(data) > max_bytes:
                raise ValueError("Fixture exceeds admitted size")
            output.write(data)
            return len(data)

        worker.download = download
        worker.execute = lambda job_id, generation: worker.run_job(
            UUID(job_id), generation, factory, settings, storage
        )
        redis = Redis.from_url(state["test_redis_url"].rsplit("/", 1)[0] + "/0")
        logging.basicConfig(level=logging.ERROR)
        print("Disposable outbox/RQ worker running with simulated AI/HTTPS only.", flush=True)
        try:
            while True:
                cleanup(factory, storage)
                worker.dispatch(factory, redis)
                SimpleWorker([Queue("ai", connection=redis)], connection=redis).work(
                    burst=True, logging_level="ERROR"
                )
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            redis.close()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
