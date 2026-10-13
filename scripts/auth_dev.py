"""Opt-in disposable native auth services. Never opens existing data directories."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(args: list[str], **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.run(args, check=True, creationflags=HIDDEN, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-disposable-local", action="store_true")
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--redis-binary", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--auth-rate-limit", type=int, default=10)
    parser.add_argument(
        "--media-test-mode",
        action="store_true",
        help="Disposable M3 chunk/allowlist fixture configuration; paid AI stays disabled",
    )
    parser.add_argument("--synthetic-media-capacity", action="store_true")
    args = parser.parse_args()
    if args.synthetic_media_capacity and not args.media_test_mode:
        parser.error("Synthetic capacity requires explicit disposable media-test-mode")
    if not args.allow_disposable_local:
        parser.error("Explicit --allow-disposable-local required")
    if not 1024 <= args.api_port <= 65535:
        parser.error("API port must be between 1024 and 65535")
    if not 1 <= args.auth_rate_limit <= 1000:
        parser.error("Auth rate limit must be between 1 and 1000")
    for port in (55438, 56388, args.api_port):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))  # Refuse occupied ports; never stop other services.
    for executable in ("initdb.exe", "pg_ctl.exe"):
        if not (args.postgres_bin / executable).is_file():
            parser.error(f"Missing {executable}")
    if not args.redis_binary.is_file():
        parser.error("Missing native Redis binary")
    work = ROOT / "var" / "phase8-auth" / uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    data = work / "postgres"
    password = secrets.token_hex(24)
    password_file = work / "init-password"
    password_file.write_text(password, encoding="utf-8")
    password_file.chmod(0o600)
    redis_process = api_process = None
    started = False
    logs = []
    try:
        with (work / "initdb.log").open("w") as log:
            run(
                [
                    str(args.postgres_bin / "initdb.exe"),
                    "-D",
                    str(data),
                    "-U",
                    "auth_dev",
                    "--auth=scram-sha-256",
                    "--encoding=UTF8",
                    "--pwfile",
                    str(password_file),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        password_file.unlink()
        run(
            [
                str(args.postgres_bin / "pg_ctl.exe"),
                "-D",
                str(data),
                "-l",
                str(work / "postgres.log"),
                "-o",
                "-h 127.0.0.1 -p 55438",
                "-w",
                "start",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started = True
        base = f"postgresql://auth_dev:{password}@127.0.0.1:55438/"
        with psycopg.connect(base + "postgres", autocommit=True) as connection:
            connection.execute("CREATE DATABASE zoclip_phase8_browser_test")
            connection.execute("CREATE DATABASE zoclip_phase8_backend_test")
        redis_log = (work / "redis.log").open("w")
        logs.append(redis_log)
        redis_process = subprocess.Popen(
            [
                str(args.redis_binary.resolve()),
                "--bind",
                "127.0.0.1",
                "--port",
                "56388",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(work),
            ],
            stdout=redis_log,
            stderr=subprocess.STDOUT,
            creationflags=HIDDEN,
        )
        with Redis(host="127.0.0.1", port=56388, socket_timeout=1) as redis:
            for attempt in range(40):
                try:
                    if redis.ping():
                        break
                except Exception:
                    if attempt == 39:
                        raise RuntimeError("Disposable Redis failed to start") from None
                    time.sleep(0.25)
        database_url = base.replace("postgresql://", "postgresql+psycopg://")
        environment = os.environ.copy()
        environment.update(
            {
                "APP_ENV": "development",
                "DATABASE_URL": database_url + "zoclip_phase8_browser_test",
                "REDIS_URL": "redis://127.0.0.1:56388/0",
                "COOKIE_SECURE": "false",
                "AUTH_RATE_LIMIT": str(args.auth_rate_limit),
                "PUBLIC_APP_URL": "http://localhost:3000",
                "API_PUBLIC_URL": f"http://localhost:{args.api_port}",
                "ALLOWED_HOSTS": '["localhost","127.0.0.1"]',
                "EMAIL_MODE": "development",
                "DEV_MAILBOX_DIR": str(work / "mailbox"),
                "MEDIA_ROOT": str(work / "media"),
                "AI_ENABLED": "false",
                "ENABLE_LIVE_PAYMENTS": "false",
                "PAYMENT_PROVIDER": "disabled",
                "ENABLE_TRIAL_CREDITS": "false",
                "GOOGLE_CLIENT_ID": "",
                "GOOGLE_CLIENT_SECRET": "",
                "GOOGLE_REDIRECT_URI": "",
                "DEEPGRAM_API_KEY": "",
                "GEMINI_API_KEY": "",
            }
        )
        if args.media_test_mode:
            environment.update(
                {"MEDIA_PART_BYTES": "65536", "MEDIA_ALLOWED_IMPORT_HOSTS": '["media.example.com"]'}
            )
        with (work / "migrate.log").open("w") as log:
            run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        state = work / "state.json"
        state.write_text(
            json.dumps(
                {
                    "database_url": environment["DATABASE_URL"],
                    "test_database_url": database_url + "zoclip_phase8_backend_test",
                    "test_redis_url": "redis://127.0.0.1:56388/15",
                    "mailbox": environment["DEV_MAILBOX_DIR"],
                    "api_origin": environment["API_PUBLIC_URL"],
                }
            ),
            encoding="utf-8",
        )
        state.chmod(0o600)
        api_log = (work / "api.log").open("w")
        logs.append(api_log)
        api_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "scripts.editor_browser_api:create_test_app"
                if args.synthetic_media_capacity
                else "zoclip.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
                "--no-access-log",
                "--no-proxy-headers",
            ],
            cwd=ROOT,
            env=environment,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            creationflags=HIDDEN,
        )
        print(
            f"Disposable auth services starting. Private state: {state.relative_to(ROOT)}",
            flush=True,
        )
        print(
            f"Loopback API: {environment['API_PUBLIC_URL']}; Ctrl+C stops these new services.",
            flush=True,
        )
        while api_process.poll() is None and redis_process.poll() is None:
            time.sleep(1)
        raise RuntimeError("A disposable service exited; inspect the private local logs")
    except KeyboardInterrupt:
        pass
    finally:
        for process in (api_process, redis_process):
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        if started:
            run(
                [
                    str(args.postgres_bin / "pg_ctl.exe"),
                    "-D",
                    str(data),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for log in logs:
            log.close()
        print("Disposable services stopped. Data/evidence preserved under var/phase8-auth.")


if __name__ == "__main__":
    main()
