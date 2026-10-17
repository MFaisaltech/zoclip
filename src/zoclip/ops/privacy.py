"""Staff-operated erasure request: revoke now; lease-aware cleanup erases media later."""

import argparse
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from zoclip.auth.mail_models import MailDelivery
from zoclip.auth.models import (
    AuthSession,
    EmailVerificationToken,
    OAuthFlow,
    OAuthIdentity,
    PasswordResetToken,
    User,
)
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.core.errors import ApiError
from zoclip.credits.service import audit, fingerprint, lock_wallet, same, staff
from zoclip.media.models import SourceVideo
from zoclip.media.service import delete_video
from zoclip.ops.models import PrivacyRequest


def request_erasure(db: Session, actor: UUID, owner: UUID, reason: str) -> None:
    staff(db, actor, reason)
    lock_wallet(db, owner, active_required=False)
    user = db.get(User, owner)
    assert user is not None
    if user.role == "admin":
        raise ApiError(409, "staff_erasure_blocked", "Resolve staff access before erasure.")
    payload = fingerprint([str(actor), reason])
    old = db.scalar(select(PrivacyRequest).where(PrivacyRequest.user_id == owner))
    if old:
        same(old.payload_hash, payload)
        return
    ids = list(
        db.scalars(
            select(SourceVideo.id)
            .where(SourceVideo.user_id == owner, SourceVideo.state != "DELETED")
            .order_by(SourceVideo.id)
            .limit(101)
        )
    )
    if len(ids) > 100:
        raise ApiError(409, "erasure_batch_required", "Delete retained sources in batches first.")
    for video_id in ids:
        # Active writers reject atomically; retry after their lease. Running jobs cancel.
        delete_video(db, owner, video_id)
    user.status, user.email, user.password_hash = (
        "disabled",
        f"erased-{owner.hex}@example.invalid",
        None,
    )
    db.execute(update(AuthSession).where(AuthSession.user_id == owner).values(revoked_at=utcnow()))
    db.execute(
        update(MailDelivery)
        .where(MailDelivery.user_id == owner)
        .values(
            state="EXPIRED",
            ciphertext=None,
            lease_until=None,
            lease_token=None,
        )
    )
    for model in (EmailVerificationToken, PasswordResetToken, OAuthFlow, OAuthIdentity):
        db.execute(delete(model).where(model.user_id == owner))
    db.add(PrivacyRequest(user_id=owner, actor_id=actor, reason=reason, payload_hash=payload))
    audit(db, actor, "privacy.erasure_requested", owner)
    db.flush()


def cleanup_auth(db: Session) -> None:
    now = utcnow()
    for model in (AuthSession, EmailVerificationToken, PasswordResetToken, OAuthFlow):
        ids = list(db.scalars(select(model.id).where(model.expires_at <= now).limit(100)))
        if ids:
            db.execute(delete(model).where(model.id.in_(ids)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", type=UUID, required=True)
    parser.add_argument("--user", type=UUID, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Review the target and case privately, then supply --execute")
    engine = build_engine(Settings().database_url.get_secret_value())  # type: ignore[call-arg]
    try:
        with Session(engine) as db:
            request_erasure(db, args.actor, args.user, args.reason)
            db.commit()
        print("Access revoked; media cleanup pending; financial history retained.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
