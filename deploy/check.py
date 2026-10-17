"""Local host checks; safe JSON only, exit nonzero for an operator alert."""

import argparse
import json
import ssl
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--project", default="zoclip-private")
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-staging", action="store_true")
    args = parser.parse_args()
    compose = [
        "docker",
        "compose",
        "--project-name",
        args.project,
        "--env-file",
        args.env_file,
        "-f",
        str(Path(__file__).parent / "compose.yaml"),
    ]
    if args.private_staging:
        compose += ["-f", str(Path(__file__).parent / "compose.private-staging.yaml")]

    def output(tail):
        return subprocess.check_output(compose + tail, stderr=subprocess.DEVNULL, timeout=60)

    alerts = []
    raw = output(["ps", "--format", "json", "--all"]).decode()
    try:
        services = json.loads(raw)
    except ValueError:
        services = [json.loads(line) for line in raw.splitlines() if line.strip()]
    # Compose versions emit either JSON lines or an array.
    if isinstance(services, dict):
        services = [services]
    for service in services:
        if service["Service"] not in ("migrate", "backup", "test-runner") and (
            service.get("State") != "running" or service.get("Health") != "healthy"
        ):
            alerts.append("service_unhealthy:" + service["Service"])
    logs = output(["logs", "--no-log-prefix", "--since", "5m", "proxy"]).decode()
    count_429 = 0
    for line in logs.splitlines():
        try:
            count_429 += json.loads(line).get("status") == 429
        except (ValueError, AttributeError):
            pass
    if count_429 >= 20:
        alerts.append("proxy_429_spike")
    backups = list(args.backup_dir.glob("????????T??????-????????.json"))
    if not backups or time.time() - max(p.stat().st_mtime for p in backups) > 26 * 3600:
        alerts.append("backup_missing_or_stale")
    certificate = ssl._ssl._test_decode_cert(str(args.certificate))
    if ssl.cert_time_to_seconds(certificate["notAfter"]) - time.time() < 14 * 86400:
        alerts.append("tls_renewal_due")
    monitor = subprocess.run(
        compose + ["exec", "-T", "maintenance", "python", "-m", "zoclip.ops.monitor"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if monitor.returncode:
        alerts.append("application_monitor_alert")
    print(json.dumps({"alerts": alerts, "proxy_429_last_5m": count_429}))
    raise SystemExit(bool(alerts))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"alerts": ["host_check_failed"], "error_class": type(exc).__name__}))
        raise SystemExit(1) from None
