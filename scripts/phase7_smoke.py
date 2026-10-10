"""Host-side LOCAL staging acceptance and failure drills. No VPS or external provider IO."""

import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path("var/phase7-verification").resolve()
PROJECT = "zoclip-phase7-verify"
COMPOSE = [
    "docker",
    "compose",
    "--project-name",
    PROJECT,
    "--env-file",
    str(ROOT / "staging.env"),
    "-f",
    "deploy/compose.yaml",
]
WORKLOAD = ["proxy", "api", "worker-ai", "worker-render", "maintenance"]


def command(args, input_text=None):
    for attempt in range(3):
        result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=300)
        # Windows can transiently fail plugin discovery before Compose executes at all.
        # Never retry an uncertain operation or a provider/SQL failure.
        if result.returncode and "unknown flag: --project-name" in result.stderr and attempt < 2:
            time.sleep(2)
            continue
        break
    if result.returncode:
        # Do not print resolved environment/config. Tool errors contain no fixture secret values.
        detail = ""
        try:
            safe_error = json.loads(result.stdout)
            if safe_error.get("state") == "failed":
                detail = str(safe_error.get("error_class", ""))
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f"Local command failed: {args[:3]}: {detail} {result.stderr[-1500:]}")
    return result.stdout


def compose(*args):
    return command(COMPOSE + list(args))


def execute(service, code):
    return compose("exec", "-T", service, "python", "-c", code)


def wait_ready(client):
    for _ in range(45):
        try:
            if client.get("/health/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("Local readiness did not recover")


def main():
    if os.environ.get("ZOCLIP_PHASE7_LOCAL_SMOKE") != "1" and sys.argv[1:] != ["--local-fixtures"]:
        raise RuntimeError("ZOCLIP_PHASE7_LOCAL_SMOKE=1 or --local-fixtures required")
    outcomes = {}
    config = json.loads(compose("config", "--format", "json"))
    for name, service in config["services"].items():
        for port in service.get("ports", []):
            assert name == "proxy" and port["host_ip"] == "127.0.0.1"
    outcomes["private_publication"] = "pass"
    print("CHECK: private publication", flush=True)
    secrets = [
        (ROOT / "private" / (role + "_password")).read_text()
        for role in ("bootstrap", "migrate", "runtime")
    ]
    ids = compose("ps", "-q").split()
    for identifier in ids:
        data = json.loads(command(["docker", "inspect", identifier]))[0]
        assert not data["State"].get("OOMKilled")
        assert data["Config"]["User"] not in ("", "0", "0:0")
        assert data["HostConfig"]["ReadonlyRootfs"]
        environment = json.dumps(data["Config"]["Env"])
        assert all(secret not in environment for secret in secrets)
    history = command(["docker", "history", "--no-trunc", "zoclip-phase7:verify"])
    assert all(secret not in history for secret in secrets)
    assert execute("api", "from pathlib import Path;assert not Path('/app/.env').exists()") == ""
    outcomes["secret_and_container_boundaries"] = "pass"
    contract = json.loads(
        execute(
            "api",
            (
                "import json,hashlib,zoclip;from pathlib import Path;"
                "from zoclip.main import create_app;root=Path(zoclip.__file__).parent;"
                "print(json.dumps({'sources':{p.relative_to(root).as_posix():"
                "hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.py')},"
                "'schema':create_app().openapi()}))"
            ),
        )
    )
    expected_sources = {
        p.relative_to(Path("src/zoclip")).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path("src/zoclip").rglob("*.py")
    }
    assert contract["sources"] == expected_sources
    assert contract["schema"] == json.loads(Path("docs/openapi.json").read_text())
    outcomes["installed_production_contract"] = {
        "sources": len(expected_sources),
        "paths": len(contract["schema"]["paths"]),
    }
    print("CHECK: secret/container boundaries and installed contract", flush=True)
    context = ssl.create_default_context(cafile=str(ROOT / "private/tls_certificate"))
    headers = {"Host": "api.zoclip.test:18443"}
    with httpx.Client(
        base_url="https://127.0.0.1:18443",
        verify=context,
        headers=headers,
        trust_env=False,
        timeout=12,
    ) as client:
        wait_ready(client)
        for path, expected in (
            ("/api/v1/me", 401),
            ("/docs", 404),
            ("/openapi.json", 404),
            ("/api/v1/admin/payments", 404),
            ("/api/v1/billing/webhooks/mock", 404),
        ):
            assert client.get(path).status_code == expected, path
        response = client.get("/health/live")
        for key in ("strict-transport-security", "x-content-type-options", "cache-control"):
            assert key in response.headers
        assert client.post("/api/v1/auth/login", content=b"x" * 16385).status_code == 413
        assert (
            client.put(
                "/api/v1/uploads/00000000-0000-0000-0000-000000000000/parts/0",
                content=b"x" * (8 * 1024**2 + 1),
            ).status_code
            == 413
        )
        assert client.get("/health/live", headers={"Host": "untrusted.invalid"}).status_code == 400
        cors = {"Origin": "https://app.zoclip.test", "Access-Control-Request-Method": "POST"}
        assert client.options("/api/v1/auth/login", headers=cors).status_code == 200
        assert (
            client.options(
                "/api/v1/auth/login", headers=cors | {"Origin": "https://evil.invalid"}
            ).status_code
            == 400
        )
        with httpx.Client(verify=context, headers=headers, trust_env=False) as admin:
            assert admin.get("https://127.0.0.1:18444/api/v1/admin/payments").status_code == 401
        try:
            httpx.get("https://127.0.0.1:18443/health/live", headers=headers, trust_env=False)
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("Untrusted fixture certificate was accepted")
        try:
            with socket.create_connection(("127.0.0.1", 18443)) as connection:
                context.wrap_socket(connection, server_hostname="wrong.invalid")
        except ssl.SSLCertVerificationError:
            pass
        else:
            raise AssertionError("Wrong TLS hostname accepted")
        outcomes["https_proxy_auth_cors_limits"] = "pass"
        print("CHECK: HTTPS/proxy/auth/CORS/request limits", flush=True)
        # Independent Linux workers and financial rollback; override only this fixture process.
        compose(
            "exec", "-T", "-e", "APP_ENV=development", "api", "python", "scripts/container_smoke.py"
        )
        seed = json.loads(
            command(
                COMPOSE
                + [
                    "exec",
                    "-T",
                    "-e",
                    "ZOCLIP_PHASE7_ISOLATED=1",
                    "api",
                    "python",
                    "-",
                ],
                input_text=Path("scripts/phase7_runtime_smoke.py").read_text(),
            )
        )
        (ROOT / "seed-evidence.json").write_text(json.dumps(seed))
        outcomes["runtime_roles_and_real_rq"] = "pass"
        print("CHECK: runtime PostgreSQL privileges, financial fixture and actual RQ", flush=True)
        time.sleep(3)
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: client.get("/health/live").status_code, range(100)))
        assert set(statuses) <= {200, 429, 503} and 200 in statuses and 429 in statuses
        outcomes["bounded_100_request_stress"] = {
            str(code): statuses.count(code) for code in set(statuses)
        }
        print("CHECK: bounded request stress", flush=True)
        time.sleep(5)
        # Stop only this project's dependency; unrelated projects and volumes remain intact.
        for dependency in ("redis", "db"):
            compose("stop", dependency)
            try:
                assert client.get("/health/ready").status_code == 503
            finally:
                compose("start", dependency)
            wait_ready(client)
            outcomes[dependency + "_outage_recovery"] = "pass"
            print("CHECK: " + dependency + " outage/recovery", flush=True)
        for worker in ("worker-ai", "worker-render", "maintenance", "api"):
            identifier = compose("ps", "-q", worker).strip()
            previous_restarts = json.loads(command(["docker", "inspect", identifier]))[0][
                "RestartCount"
            ]
            # Docker kill is an explicit operator stop and suppresses restart in some
            # engines. Crash the init process's application child instead.
            crash_code = (
                "import os,signal;from pathlib import Path;"
                "pid=int(Path('/proc/1/task/1/children').read_text().split()[0]);"
                "os.kill(pid,signal.SIGKILL)"
            )
            triggered = subprocess.run(
                ["docker", "exec", identifier, "python", "-c", crash_code],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if triggered.returncode not in (0, 137):
                raise RuntimeError("Application crash trigger failed")
            # Restart policy recovery, not manual start; allow dependency health to settle.
            for _ in range(45):
                state = json.loads(command(["docker", "inspect", identifier]))[0]
                if state["State"]["Running"] and state["RestartCount"] > previous_restarts:
                    break
                time.sleep(1)
            else:
                raise AssertionError(worker + " did not restart")
            wait_ready(client)
            outcomes[worker + "_crash_restart"] = "pass"
            print("CHECK: " + worker + " crash/restart", flush=True)
        compose(
            "exec", "-T", "-e", "APP_ENV=development", "api", "python", "scripts/container_smoke.py"
        )
        compose("exec", "-T", "api", "alembic", "check")
        outcomes["post_recovery_rq_migration"] = "pass"
    # Quiesce writers/maintenance and backup a consistent DB/media pair.
    compose("stop", *WORKLOAD)
    print("CHECK: writers quiesced for encrypted backup", flush=True)
    raw = compose("run", "--rm", "--no-deps", "-e", "BACKUP_QUIESCED=1", "backup")
    backup_name = json.loads(raw)["backup"]
    compose("run", "--rm", "--no-deps", "backup", "verify", "--manifest", backup_name)
    print("CHECK: encrypted backup and ciphertext checksums", flush=True)
    suffix = uuid4().hex[:8]
    restore_database = "zoclip_phase7_" + suffix + "_restore_test"
    command(
        [
            "docker",
            "exec",
            PROJECT + "-db-1",
            "psql",
            "-U",
            "zoclip_bootstrap",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE DATABASE " + restore_database + " OWNER zoclip_migrate",
        ]
    )
    private = ROOT / "private"
    restore_volume = PROJECT + "_restore_media_" + suffix
    command(["docker", "volume", "create", restore_volume])
    # Empty restore volume ownership only; never changes existing media or customer data.
    command(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "--network",
            "none",
            "--entrypoint",
            "chown",
            "-v",
            restore_volume + ":/restore-media",
            "zoclip-ops:phase7",
            "10001:10001",
            "/restore-media",
        ]
    )
    restore_command = [
        "docker",
        "run",
        "--rm",
        "--network",
        PROJECT + "_data",
        "-e",
        "PGHOST=db",
        "-e",
        "PGUSER=zoclip_migrate",
        "-e",
        "PGDATABASE=" + restore_database,
        "-e",
        "PGPASSFILE=/run/secrets/backup_pgpass",
        "-v",
        str(private / "backup_pgpass") + ":/run/secrets/backup_pgpass:ro",
        "-v",
        str(private / ("restore_identity_" + suffix)) + ":/run/secrets/backup_identity:ro",
        "-v",
        str(ROOT / "backups") + ":/backups:ro",
        "-v",
        restore_volume + ":/restore-media",
        "zoclip-ops:phase7",
        "restore",
        "--manifest",
        backup_name,
    ]
    # The offline original stays 0600. A temporary single-file mount is readable
    # by restore UID10001 inside the host's private0700 directory, then erased.
    identity = private / ("restore_identity_" + suffix)
    with identity.open("xb") as stream:
        stream.write((private / "backup_identity").read_bytes())
    identity.chmod(0o444)
    try:
        command(restore_command)
        # Refuse populated target; never pg_restore --clean or database drops.
        refusal = subprocess.run(restore_command, capture_output=True, text=True)
        assert refusal.returncode != 0
    finally:
        identity.chmod(0o600)
        identity.unlink()
    print("CHECK: separate-target restore and overwrite refusal", flush=True)
    ledger = command(
        [
            "docker",
            "exec",
            PROJECT + "-db-1",
            "psql",
            "-U",
            "zoclip_bootstrap",
            "-d",
            restore_database,
            "-Atc",
            "SELECT id, available_delta, reserved_delta FROM wallet_transactions ORDER BY id",
        ]
    )
    expected = "".join("|".join(map(str, row)) + "\n" for row in seed["ledger"])
    assert ledger == expected
    restored = [
        "docker",
        "exec",
        PROJECT + "-db-1",
        "psql",
        "-U",
        "zoclip_bootstrap",
        "-d",
        restore_database,
        "-Atc",
    ]
    assert command(restored + ["SELECT version_num FROM alembic_version"]).strip() == "7b37ea061d28"
    reconciliation = (
        "SELECT count(*) FROM wallets w WHERE w.available <> COALESCE("
        "(SELECT sum(t.available_delta) FROM wallet_transactions t WHERE t.user_id=w.user_id),0) "
        "OR w.reserved <> COALESCE((SELECT sum(t.reserved_delta) FROM wallet_transactions t "
        "WHERE t.user_id=w.user_id),0)"
    )
    assert command(restored + [reconciliation]).strip() == "0"
    code = (
        "import hashlib;print(hashlib.sha256("
        "open('/restore-media/phase7-restore-fixture.bin','rb').read()).hexdigest())"
    )
    media_hash = command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python3",
            "-v",
            restore_volume + ":/restore-media:ro",
            "zoclip-ops:phase7",
            "-c",
            code,
        ]
    ).strip()
    assert media_hash == seed["media_sha256"]
    outcomes["encrypted_backup_restore_and_overwrite_refusal"] = "pass"
    outcomes["backup_manifest"] = backup_name
    outcomes["restore_database"] = restore_database
    outcomes["restore_media_volume"] = restore_volume
    compose("up", "--detach", "--wait", "--wait-timeout", "180")
    (ROOT / "infrastructure-results.json").write_text(json.dumps(outcomes, indent=2))
    print(json.dumps(outcomes, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"LOCAL SMOKE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
