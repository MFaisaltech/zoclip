"""Linux-only disposable Phase 1–3 regression runner, never a deployment command."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    database = os.environ.get("TEST_DATABASE_URL", "")
    redis = os.environ.get("TEST_REDIS_URL", "")
    if (
        sys.platform != "linux"
        or not database.startswith("postgresql+psycopg://")
        or not urlsplit(database).path.endswith("_test")
        or not redis.endswith("/15")
    ):
        raise RuntimeError("Linux, disposable PostgreSQL _test DB and Redis DB 15 required")
    root = Path.cwd()
    output_dir = Path(
        os.environ.get("ZOCLIP_VERIFICATION_OUTPUT", str(root / "var/phase3-completion"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        # Compose's HTTP/development-email settings must not leak into config tests.
        APP_ENV="test",
        COOKIE_SECURE="true",
        EMAIL_MODE="disabled",
        UV_CACHE_DIR=str(output_dir / "uv-cache"),
        UV_PROJECT_ENVIRONMENT="/tmp/verification-venv",
        UV_LINK_MODE="copy",
        PYTHONPATH=str(root / "src"),
        PYTHONPYCACHEPREFIX="/tmp/verification-pycache",
    )
    # Dependency downloads use system roots, independently of the fixture-only CA.
    install_env = {**os.environ, "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"}
    subprocess.run(["uv", "sync", "--frozen"], env=install_env, check=True)
    python = "/tmp/verification-venv/bin/python"
    commands = [
        [python, "-m", "ruff", "check", "--no-cache", "src", "tests", "scripts", "alembic"],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "--no-cache",
            "src",
            "tests",
            "scripts",
            "alembic",
        ],
        [python, "-m", "mypy", "--cache-dir=/tmp/verification-mypy", "src"],
        [
            python,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--basetemp=/tmp/phase3-tests",
            "-p",
            "no:cacheprovider",
            "--junitxml=" + str(output_dir / "pytest.xml"),
        ],
    ]
    with (output_dir / "linux-final.log").open("w", encoding="utf-8") as output:
        status_path = output_dir / "gate-status.json"
        status_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
        for command in commands:
            label = "COMMAND: " + " ".join(command)
            print(label, flush=True)
            output.write(label + "\n")
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            print(result.stdout, flush=True)
            output.write(result.stdout)
            output.flush()
            if result.returncode:
                status_path.write_text(
                    json.dumps(
                        {"state": "failed", "command": command, "exit_code": result.returncode}
                    ),
                    encoding="utf-8",
                )
                raise SystemExit(result.returncode)
        status_path.write_text(json.dumps({"state": "passed"}), encoding="utf-8")


if __name__ == "__main__":
    main()
