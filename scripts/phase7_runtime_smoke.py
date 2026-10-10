"""Disposable Phase 7 container fixture only; no provider calls. Never use on customer data."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import build_engine
from zoclip.credits import service
from zoclip.credits.models import CreditTransaction, Wallet


def main():
    if os.environ.get("ZOCLIP_PHASE7_ISOLATED") != "1":
        raise RuntimeError("Disposable local Phase 7 opt-in required")
    settings = Settings()
    if settings.api_public_url != "https://api.zoclip.test:18443":
        raise RuntimeError("Only the generated fictional local fixture origin is allowed")
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as db:
            assert db.scalar(text("SELECT current_user")) == "zoclip_runtime"
        for sql in (
            "CREATE TABLE should_be_forbidden(id int)",
            "UPDATE alembic_version SET version_num = 'forged'",
            "DELETE FROM wallet_transactions",
            "TRUNCATE admin_audit_logs",
        ):
            with engine.begin() as db:
                try:
                    db.execute(text(sql))
                except DBAPIError:
                    pass
                else:
                    raise AssertionError("Runtime privilege boundary missing")
        with Session(engine) as db:
            actor = User(
                email=f"phase7-staff-{uuid4()}@example.invalid", verified=True, role="admin"
            )
            owner = User(email=f"phase7-owner-{uuid4()}@example.invalid", verified=True)
            db.add_all([actor, owner])
            db.flush()
            a = service.adjust(
                db,
                owner.id,
                3,
                "phase7-fixture",
                actor.id,
                "Disposable Phase7 fixture grant",
                grant=True,
            )
            b = service.adjust(
                db,
                owner.id,
                3,
                "phase7-fixture",
                actor.id,
                "Disposable Phase7 fixture grant",
                grant=True,
            )
            assert a.id == b.id
            db.commit()
        path = Path(settings.media_root) / "phase7-restore-fixture.bin"
        path.write_bytes(b"fictional-private-media-backup-fixture")
        with Session(engine) as db:
            for wallet in db.scalars(select(Wallet)):
                service.reconcile(db, wallet)
            rows = [
                (str(row.id), row.available_delta, row.reserved_delta)
                for row in db.scalars(select(CreditTransaction).order_by(CreditTransaction.id))
            ]
        print(
            json.dumps(
                {
                    "runtime_privileges": "pass",
                    "ledger": rows,
                    "media_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
