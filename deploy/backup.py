"""Encrypted, quiesced backups and empty-target restores. No automatic destructive overwrite."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


def run(args, **kwargs):
    return subprocess.run(args, check=True, stderr=subprocess.PIPE, timeout=1800, **kwargs)


def finish(source):
    source.stdout.close()
    try:
        return source.wait(timeout=30)
    except subprocess.TimeoutExpired:
        source.kill()
        source.wait(timeout=10)
        raise RuntimeError("Backup stream failed to terminate") from None


def encrypt(args, output):
    source = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        run(["age", "-R", "/run/secrets/backup_recipient", "-o", str(output)], stdin=source.stdout)
    finally:
        if finish(source) != 0:
            raise RuntimeError("Backup source failed")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup(root):
    if os.environ.get("BACKUP_QUIESCED") != "1":
        raise RuntimeError("Stop API, workers and maintenance before backup")
    root.mkdir(parents=True, exist_ok=True)
    # No plaintext dump or tar lands on disk; reserve a conservative encrypted envelope.
    media_bytes = sum(p.stat().st_size for p in Path("/media").rglob("*") if p.is_file())
    db_bytes = int(
        run(
            ["psql", "-Atc", "SELECT pg_database_size(current_database())"], stdout=subprocess.PIPE
        ).stdout
    )
    if shutil.disk_usage(root).free < 20 * 1024**3 + 2 * (media_bytes + db_bytes):
        raise RuntimeError("Insufficient backup disk headroom")
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + os.urandom(4).hex()
    pending = []
    files = {}
    try:
        for suffix, command in (
            ("db.age", ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]),
            ("media.age", ["tar", "-C", "/media", "-cf", "-", "."]),
        ):
            part = root / (name + "." + suffix + ".part")
            pending.append(part)
            encrypt(command, part)
            with part.open("rb") as stream:
                os.fsync(stream.fileno())
            target = part.with_suffix("")
            part.rename(target)
            pending.append(target)
            files[target.name] = digest(target)
        manifest = {
            "format": 1,
            "files": files,
            "quiesced": True,
            "created_at": datetime.now(UTC).isoformat(),
        }
        part = root / (name + ".json.part")
        pending.append(part)
        with part.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        target = part.with_suffix("")
        part.rename(target)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        print(json.dumps({"backup": target.name, "state": "encrypted"}))
    except BaseException:
        for path in pending:
            path.unlink(missing_ok=True)
        raise


def verify(root, name):
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[a-f0-9]{8}\.json", name):
        raise ValueError("Invalid backup manifest name")
    doc = json.loads((root / name).read_text())
    expected = {name[:-5] + ".db.age", name[:-5] + ".media.age"}
    if set(doc["files"]) != expected or not doc.get("quiesced") or doc.get("format") != 1:
        raise ValueError("Invalid backup manifest")
    for filename, wanted in doc["files"].items():
        if digest(root / filename) != wanted:
            raise ValueError("Backup checksum mismatch")
    return doc


def extract_media(archive, media):
    root = media.resolve()
    for item in archive:
        relative = PurePosixPath(item.name)
        if (
            not (item.isfile() or item.isdir())
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in item.name
            or ":" in item.name
            or "\x00" in item.name
        ):
            raise RuntimeError("Unsafe media archive")
        target = root.joinpath(*relative.parts).resolve()
        if not target.is_relative_to(root) or (item.isfile() and target == root):
            raise RuntimeError("Unsafe media archive")
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            continue
        if shutil.disk_usage(root).free < 20 * 1024**3 + item.size:
            raise RuntimeError("Insufficient restore disk headroom")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = archive.extractfile(item)
        if source is None:
            raise RuntimeError("Missing archive file")
        # Never restore archived owners/modes or overwrite an existing file.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with source, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(source, output, length=65536)
            output.flush()
            os.fsync(output.fileno())


def restore(root, name, media):
    verify(root, name)
    database = os.environ.get("PGDATABASE", "")
    if not database.endswith(("_restore", "_restore_test")):
        raise RuntimeError("A separately created empty *_restore target database is required")
    tables = run(
        [
            "psql",
            "-Atc",
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S','v')",
        ],
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if tables != b"0" or media.exists() and any(media.iterdir()):
        raise RuntimeError("Restore requires empty database and media directory")
    media.mkdir(parents=True, exist_ok=True)
    source = subprocess.Popen(
        ["age", "-d", "-i", "/run/secrets/backup_identity", str(root / (name[:-5] + ".db.age"))],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        run(
            [
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
                "--dbname",
                database,
            ],
            stdin=source.stdout,
        )
    finally:
        if finish(source) != 0:
            raise RuntimeError("Database decryption failed; discard this restore target")
    source = subprocess.Popen(
        ["age", "-d", "-i", "/run/secrets/backup_identity", str(root / (name[:-5] + ".media.age"))],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        with tarfile.open(fileobj=source.stdout, mode="r|") as archive:
            extract_media(archive, media)
        # Consume archive padding and authenticated stream EOF before closing age's pipe.
        while source.stdout.read(65536):
            pass
    finally:
        if finish(source) != 0:
            raise RuntimeError("Media decryption failed; discard this restore target")
    print(json.dumps({"state": "restored", "database": database}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "verify", "restore"])
    parser.add_argument("--manifest")
    parser.add_argument("--root", type=Path, default=Path("/backups"))
    parser.add_argument("--media", type=Path, default=Path("/restore-media"))
    args = parser.parse_args()
    os.umask(0o077)
    # Compose bind mounts cannot reliably set modes; libpq requires a 0600 pgpass file.
    pgpass = Path("/tmp") / ("zoclip-pgpass-" + os.urandom(8).hex())
    try:
        with pgpass.open("x", encoding="utf-8") as stream:
            stream.write(Path(os.environ["PGPASSFILE"]).read_text())
        pgpass.chmod(0o600)
        os.environ["PGPASSFILE"] = str(pgpass)
        if args.action == "backup":
            backup(args.root)
        elif args.action == "verify":
            verify(args.root, args.manifest)
            print('{"state":"checksums_verified"}')
        else:
            restore(args.root, args.manifest, args.media)
    finally:
        pgpass.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never echo provider config, SQL, subprocess stderr or archive paths.
        print(json.dumps({"state": "failed", "error_class": type(exc).__name__}))
        raise SystemExit(1) from None
