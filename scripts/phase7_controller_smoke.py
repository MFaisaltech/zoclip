"""LOCAL controller/backup/alert safeguards, after the isolated infrastructure drill."""

import json
import ssl
import subprocess
import sys
from uuid import uuid4

import httpx
from phase7_smoke import COMPOSE, PROJECT, ROOT, command


def main():
    if sys.argv[1:] != ["--local-fixtures"]:
        raise RuntimeError("--local-fixtures required; no server execution")
    assert json.loads((ROOT / "gate-status.json").read_text())["state"] == "passed"
    assert (ROOT / "infrastructure-results.json").is_file()
    case = ROOT / ("controller-case-" + uuid4().hex)
    case.mkdir()
    metadata = (ROOT / "staging.env").read_text()
    assert "https://api.zoclip.test:18443" in metadata
    (case / "staging.env").write_text(metadata)
    base = [sys.executable, "deploy/manage.py"]
    options = ["--env-file", str(case / "staging.env"), "--project", PROJECT]
    marker = case / "rollout-approved.json"

    def reject(arguments, message):
        result = subprocess.run(base + arguments, capture_output=True, text=True, timeout=240)
        assert result.returncode != 0 and message in result.stderr, result.stderr[-1000:]

    reject(["up", *options], "--execute-local is required")
    old_migration = command(
        ["docker", "inspect", "--format", "{{.State.StartedAt}}", PROJECT + "-migrate-1"]
    )
    marker.write_text(
        json.dumps(
            {
                "project": PROJECT,
                "image": "zoclip-phase7:verify",
                "new_empty_database": True,
            }
        )
    )
    # This must stop writers and refuse before migration on an already populated schema.
    reject(["up", *options, "--execute-local"], "New-empty approval cannot bypass backup")
    command(base + ["resume", *options, "--execute-local"])
    assert (
        command(["docker", "inspect", "--format", "{{.State.StartedAt}}", PROJECT + "-migrate-1"])
        == old_migration
    )
    previous = "zoclip-phase7@sha256:" + "1" * 64
    context = ssl.create_default_context(cafile=str(ROOT / "private/tls_certificate"))
    response = httpx.get(
        "https://127.0.0.1:18443/health/ready",
        verify=context,
        trust_env=False,
        headers={"Host": "api.zoclip.test:18443"},
    )
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["cache-control"] == "no-store"
    marker.write_text(
        json.dumps(
            {
                "project": PROJECT,
                "image": previous,
                "backup_verified": True,
                "schema_compatible": False,
            }
        )
    )
    reject(
        [
            "rollback",
            *options,
            "--execute-local",
            "--previous-image",
            previous,
        ],
        "current schema",
    )
    refused_backup = subprocess.run(
        COMPOSE + ["run", "--rm", "--no-deps", "backup"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert refused_backup.returncode != 0
    assert json.loads(refused_backup.stdout)["error_class"] == "RuntimeError"
    alerts = subprocess.run(
        [
            sys.executable,
            "deploy/check.py",
            "--env-file",
            str(ROOT / "staging.env"),
            "--project",
            PROJECT,
            "--backup-dir",
            str(ROOT / "backups"),
            "--certificate",
            str(ROOT / "private/tls_certificate"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    observed = json.loads(alerts.stdout)
    assert alerts.returncode == 1 and "tls_renewal_due" in observed["alerts"]
    assert set(observed["alerts"]) <= {"tls_renewal_due", "proxy_429_spike"}, observed
    results = {
        "explicit_execution_required": "pass",
        "populated_database_rejects_new_empty_shortcut": "pass",
        "resume_existing_containers_without_migration": "pass",
        "single_proxy_security_headers": "pass",
        "rollback_requires_current_schema_compatibility": "pass",
        "backup_requires_quiescence": "pass",
        "local_alert_exit_and_fixture_tls_expiry": observed,
        "previous_image_rollout": "not attempted: no prior verified Phase 7 release",
    }
    (ROOT / "controller-results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
