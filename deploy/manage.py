"""Local-host-only deployment controller. Never SSHs, publishes ports or deletes volumes."""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from uuid import UUID

WORKLOAD = ["proxy", "api", "worker-ai", "worker-render", "maintenance"]


def validate_private_config(config):
    for name in ["api", "proxy", "backup"]:
        if not re.fullmatch(r".+@sha256:[a-f0-9]{64}", config["services"][name]["image"]):
            raise RuntimeError("Private staging requires reviewed app, proxy and tools digests")
    for name in ["api", "worker-ai", "worker-render", "maintenance", "migrate"]:
        env = config["services"][name]["environment"]
        try:
            UUID(str(env.get("STAGING_INVITE_EPOCH", "")))
        except ValueError as exc:
            raise RuntimeError(
                "Private staging requires an owner-selected invite epoch UUID"
            ) from exc
        if any(
            env.get(key) != value
            for key, value in {
                "PRIVATE_STAGING": "true",
                "AI_ENABLED": "false",
                "REGISTRATION_ENABLED": "false",
                "PAYMENT_PROVIDER": "disabled",
                "ENABLE_LIVE_PAYMENTS": "false",
                "ENABLE_TRIAL_CREDITS": "false",
                "DEEPGRAM_API_KEY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_CLIENT_ID": "",
                "GOOGLE_CLIENT_SECRET": "",
                "GOOGLE_REDIRECT_URI": "",
                "EMAIL_MODE": "disabled",
                "MEDIA_ALLOWED_IMPORT_HOSTS": "[]",
            }.items()
        ):
            raise RuntimeError("Private staging integrations must remain closed")
    for name in ["api", "worker-ai", "worker-render", "maintenance", "migrate"]:
        networks = config["services"][name]["networks"]
        if any(not config["networks"][network].get("internal") for network in networks):
            raise RuntimeError("Private staging application networks must be internal")
    mounts = config["services"]["proxy"]["volumes"]
    if not any(
        mount["target"] == "/etc/nginx/nginx.conf"
        and Path(mount["source"]).name == "nginx.private-staging.conf"
        and mount.get("read_only")
        for mount in mounts
    ):
        raise RuntimeError("Private staging requires the reviewed single-origin proxy profile")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "up", "resume", "stop", "backup", "rollback"])
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project", default="zoclip-private")
    parser.add_argument("--execute-local", action="store_true")
    parser.add_argument("--private-staging", action="store_true")
    parser.add_argument("--previous-image")
    args = parser.parse_args()
    if not args.project.startswith("zoclip-"):
        parser.error("Use a named isolated zoclip- project")
    if args.action != "plan" and not args.execute_local:
        parser.error("--execute-local is required; VPS execution needs separate user authorization")
    environment = dict(os.environ)
    if args.previous_image:
        if args.action != "rollback" or "@sha256:" not in args.previous_image:
            parser.error("Rollback requires a previously recorded compatible image digest")
        environment["APP_IMAGE"] = args.previous_image
    elif args.action == "rollback":
        parser.error("--previous-image required; schema downgrade is never automatic")
    compose = [
        "docker",
        "compose",
        "--project-name",
        args.project,
        "--env-file",
        str(args.env_file),
        "-f",
        str(Path(__file__).parent / "compose.yaml"),
    ]
    if args.private_staging:
        compose += ["-f", str(Path(__file__).parent / "compose.private-staging.yaml")]
    # Capture configuration privately; do not print environment or resolved secrets paths.
    config = json.loads(
        subprocess.check_output(
            compose + ["--profile", "tools", "config", "--format", "json"], env=environment
        )
    )
    for name, service in config["services"].items():
        for port in service.get("ports", []):
            if name != "proxy" or port.get("host_ip") != "127.0.0.1":
                raise RuntimeError("Only loopback proxy publication is authorized")
    if args.private_staging:
        validate_private_config(config)
    print(
        json.dumps(
            {
                "project": args.project,
                "services": list(config["services"]),
                "publication": "loopback HTTPS/admin only",
                "action": args.action,
                "private_staging": args.private_staging,
            }
        ),
        flush=True,
    )
    if args.action == "plan":
        return
    if args.action in ("up", "rollback") and args.project != "zoclip-phase7-verify":
        if "@sha256:" not in config["services"]["api"]["image"]:
            raise RuntimeError("Server rollout requires an immutable application image digest")

    def call(tail):
        subprocess.run(compose + tail, env=environment, check=True)

    if args.action == "stop":
        call(["stop"])
    elif args.action == "resume":
        # Existing reviewed installation only; refuse recreation or implicit migration on boot.
        call(["start", "--wait", "--wait-timeout", "180", "db", "redis"])
        identifiers = []
        for service in WORKLOAD:
            existing = (
                subprocess.check_output(
                    compose + ["ps", "--all", "--quiet", service], env=environment
                )
                .decode()
                .split()
            )
            if len(existing) != 1:
                raise RuntimeError("Resume requires exactly one existing container per service")
            identifiers.extend(existing)
        # Compose start follows depends_on and can rerun a completed migrator.
        # Docker start targets only these reviewed existing workload containers.
        subprocess.run(["docker", "start", *identifiers], check=True)
        for _ in range(90):
            states = json.loads(subprocess.check_output(["docker", "inspect", *identifiers]))
            if all(s["State"].get("Health", {}).get("Status") == "healthy" for s in states):
                break
            time.sleep(2)
        else:
            raise RuntimeError("Resumed workload did not become healthy")
    elif args.action == "backup":
        call(["stop", *WORKLOAD])
        call(["run", "--rm", "--no-deps", "-e", "BACKUP_QUIESCED=1", "backup"])
        print(
            "Backup complete. Workload remains stopped; verify/copy ciphertext before restarting."
        )
    else:
        # Migrator must have a completed backup and reviewed compatible schema before upgrades.
        # This controller does not claim a database backup exists: operator gate is explicit.
        marker = args.env_file.parent / "rollout-approved.json"
        approval = json.loads(marker.read_text())
        if (
            approval.get("project") != args.project
            or approval.get("image") != config["services"]["api"]["image"]
        ):
            raise RuntimeError("Reviewed rollout-approved.json must match project and exact image")
        if not approval.get("backup_verified") and not approval.get("new_empty_database"):
            raise RuntimeError("Verified backup or explicitly new empty database required")
        if args.action == "rollback" and not approval.get("schema_compatible"):
            raise RuntimeError("Rollback requires reviewed compatibility with the current schema")
        call(["stop", *WORKLOAD])
        call(["up", "--detach", "--wait", "--wait-timeout", "180", "db", "redis"])
        if args.action == "up" and not approval.get("backup_verified"):
            count = subprocess.check_output(
                compose
                + [
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "zoclip_bootstrap",
                    "-d",
                    "zoclip",
                    "-Atc",
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
                ],
                env=environment,
            ).strip()
            if count != b"0":
                raise RuntimeError("New-empty approval cannot bypass backup for an existing schema")
        if args.action == "up":
            call(["run", "--rm", "--no-deps", "migrate"])
        call(["up", "--detach", "--no-deps", "--wait", "--wait-timeout", "180", *WORKLOAD])


if __name__ == "__main__":
    main()
