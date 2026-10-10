"""Create fictional LOCAL fixtures only; never reads existing credentials or contacts a VPS."""

import ipaddress
import json
import os
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main():
    if os.environ.get("ZOCLIP_PHASE7_LOCAL_FIXTURES") != "1":
        raise RuntimeError("Explicit local fixture opt-in required")
    root = Path("var/phase7-verification").resolve()
    private = root / "private"
    private.mkdir(parents=True, mode=0o700, exist_ok=False)
    (root / "backups").mkdir()
    for role in ("bootstrap", "migrate", "runtime"):
        password = secrets.token_hex(32)
        (private / (role + "_password")).write_text(password)
        if role != "bootstrap":
            (private / (role + "_database_url")).write_text(
                f"postgresql+psycopg://zoclip_{role}:{password}@db:5432/zoclip"
            )
        if role == "migrate":
            (private / "backup_pgpass").write_text(f"db:5432:*:zoclip_migrate:{password}\n")
    (private / "reporting_policy").write_text('{"enabled": false}')
    bootstrap = (private / "bootstrap_password").read_text()
    (private / "test_database_url").write_text(
        f"postgresql+psycopg://zoclip_bootstrap:{bootstrap}@db:5432/zoclip_phase7_linux_test"
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ZoClip local Phase7 fixture")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("api.zoclip.test"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (private / "tls_certificate").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (private / "tls_key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "0",
        "--network",
        "none",
        "--entrypoint",
        "age-keygen",
        "-v",
        str(private) + ":/private",
        "zoclip-ops:phase7",
    ]
    subprocess.run(
        command + ["-o", "/private/backup_identity"],
        check=True,
        capture_output=True,
    )
    recipient = subprocess.check_output(command + ["-y", "/private/backup_identity"]).decode()
    (private / "backup_recipient").write_text(recipient)
    # Containing directory is 0700 on Linux; single-file mounts must be readable by service UID.
    for file in private.iterdir():
        file.chmod(0o444 if file.name != "backup_identity" else 0o600)
    values = {
        "APP_IMAGE": "zoclip-phase7:verify",
        "OPS_IMAGE": "zoclip-ops:phase7",
        "NGINX_IMAGE": (
            "nginx@sha256:552e7481ca93ffccd046aa658dbbed22caefbc09c66fa7cd247cbb90b8a5c609"
        ),
        "PRIVATE_DIR": private.as_posix(),
        "BACKUP_DIR": (root / "backups").as_posix(),
        "PUBLIC_APP_URL": "https://app.zoclip.test",
        "API_PUBLIC_URL": "https://api.zoclip.test:18443",
        "ALLOWED_HOSTS": '["api.zoclip.test"]',
        "STAGING_HTTPS_PORT": "18443",
        "STAGING_ADMIN_PORT": "18444",
    }
    (root / "staging.env").write_text("\n".join(k + "=" + v for k, v in values.items()) + "\n")
    (root / "rollout-approved.json").write_text(
        json.dumps(
            {
                "project": "zoclip-phase7-verify",
                "image": values["APP_IMAGE"],
                "new_empty_database": True,
            }
        )
    )
    print("Created ignored local synthetic fixtures. No private key/password was printed.")


if __name__ == "__main__":
    main()
