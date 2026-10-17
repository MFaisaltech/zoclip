"""Operator CLI. Plan is read-only; issue/revoke require explicit later authorization."""

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from zoclip.auth.models import StagingInvite
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.ops.staging_accounts import (
    InviteApproval,
    check_approval,
    event,
    issue,
    revoke,
    revoke_reviewer,
    target_hash,
)


def write_token(path: Path, raw: str) -> None:
    if os.name != "posix":
        raise ValueError("Production token delivery requires Linux private filesystem permissions")
    parent = path.parent.stat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_mode & 0o077
        or parent.st_uid != os.geteuid()  # type: ignore[attr-defined] # Linux-only, guarded above.
        or path.parent.is_symlink()
    ):
        raise ValueError("Token parent must be a private0700 directory owned by this UID")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,  # type: ignore[attr-defined]
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(raw + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)  # type: ignore[attr-defined]
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["target", "plan", "issue", "inspect", "revoke", "revoke-reviewer"]
    )
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--token-output", type=Path)
    parser.add_argument("--operation", type=UUID)
    parser.add_argument("--actor", type=UUID)
    parser.add_argument("--authority-evidence-sha256")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    if (
        not settings.private_staging
        or settings.app_env != "production"
        or settings.staging_invite_epoch is None
    ):
        parser.error("Only production private staging is supported; never acceptance environments")
    if args.action == "target":
        print(json.dumps({"target_sha256": target_hash(settings)}))
        return
    if args.action in {"issue", "revoke", "revoke-reviewer"} and not args.execute:
        parser.error("Explicit operator approval and --execute required")
    approval, approval_hash = None, None
    if args.action in {"plan", "issue"}:
        if not args.approval:
            parser.error("--approval required")
        raw = args.approval.read_bytes()
        approval_hash = hashlib.sha256(raw).hexdigest()
        approval = InviteApproval.model_validate_json(raw)
        check_approval(settings, approval)
        if args.action == "plan":
            print(
                json.dumps(
                    {
                        "operation": str(approval.operation_id),
                        "approval_sha256": approval_hash,
                        "purpose": approval.purpose,
                        "state": "validated_only_no_database_write",
                    }
                )
            )
            return
        if (
            not args.token_output
            or not args.expected_sha256
            or not re.fullmatch(r"[a-f0-9]{64}", args.expected_sha256)
            or args.expected_sha256 != approval_hash
        ):
            parser.error("Reviewed exact --expected-sha256 and private --token-output required")
    elif not args.operation:
        parser.error("--operation required")
    if args.action in {"revoke", "revoke-reviewer"}:
        if not re.fullmatch(r"[a-f0-9]{64}", args.authority_evidence_sha256 or ""):
            parser.error("Private revocation authority --authority-evidence-sha256 required")
        if args.action == "revoke-reviewer" and not args.actor:
            parser.error("--actor admin required")
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            if args.action == "issue":
                assert approval is not None and approval_hash is not None
                invite, secret = issue(db, settings, approval, approval_hash)
                # Persist private delivery BEFORE commit. On any ambiguous failure keep this
                # artifact; inspect durable status, never regenerate or auto-retry this operation.
                write_token(args.token_output, secret)
                db.commit()
                print(json.dumps({"operation": str(invite.id), "state": "issued"}))
            elif args.action in {"revoke", "revoke-reviewer"}:
                if args.action == "revoke":
                    revoke(db, settings, args.operation, args.actor)
                else:
                    revoke_reviewer(db, settings, args.operation, args.actor)
                revoked = db.get(StagingInvite, args.operation)
                assert revoked is not None
                event(db, revoked, "staging.revoke:" + args.authority_evidence_sha256, args.actor)
                db.commit()
                print(json.dumps({"operation": str(args.operation), "state": "revoked"}))
            else:
                found = db.get(StagingInvite, args.operation)
                print(
                    json.dumps(
                        {
                            "operation": str(args.operation),
                            "state": "absent"
                            if not found
                            else "consumed"
                            if found.consumed_at
                            else "revoked"
                            if found.revoked_at
                            else "issued",
                            "expires_at": found.expires_at.isoformat() if found else None,
                        }
                    )
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "state": "failed_or_uncertain_inspect_before_retry",
                    "error_class": type(exc).__name__,
                }
            )
        )
        raise SystemExit(1) from None
