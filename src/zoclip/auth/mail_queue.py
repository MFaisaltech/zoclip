"""Encrypted PostgreSQL outbox; bounded, at-least-once SMTP delivery.

A lost acknowledgement can repeat an email, never a financial operation. Row locks
and persisted leases prevent concurrent sends; expired leases survive restarts.
"""

import base64
import json
import os
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from zoclip.auth.email import SMTPEmail
from zoclip.auth.mail_models import MailDelivery
from zoclip.auth.models import EmailVerificationToken, PasswordResetToken, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import digest


def _cipher(settings: Settings) -> AESGCM:
    return AESGCM(
        base64.b64decode(settings.email_queue_key.get_secret_value(), altchars=b"-_", validate=True)
    )


def _aad(row: MailDelivery) -> bytes:
    return f"zoclip-mail-v1:{row.id}:{row.user_id}:{row.purpose}".encode()


def enqueue(db: Session, settings: Settings, user: User, purpose: str, raw: str) -> bool:
    """Call under the issuing user's row lock, in the token transaction."""
    if settings.email_mode != "smtp":
        raise ValueError("SMTP queue is unavailable")
    if purpose not in {"verify-email", "password-reset"}:
        raise ValueError("Unsupported email purpose")
    model: type[EmailVerificationToken] | type[PasswordResetToken] = (
        EmailVerificationToken if purpose == "verify-email" else PasswordResetToken
    )
    db.flush()
    issued = cast(
        EmailVerificationToken | PasswordResetToken | None,
        db.scalar(select(model).where(model.user_id == user.id, model.token_hash == digest(raw))),
    )
    if not issued or issued.consumed_at or issued.expires_at <= utcnow():
        raise ValueError("A valid issued token is required")
    operation = f"{purpose}:{digest(raw)}"
    if db.scalar(select(MailDelivery.id).where(MailDelivery.operation_key == operation)):
        return True
    # Superseded links must never leave a backlog of deliverable stale emails.
    for old in db.scalars(
        select(MailDelivery)
        .where(
            MailDelivery.user_id == user.id,
            MailDelivery.purpose == purpose,
            MailDelivery.state == "QUEUED",
        )
        .with_for_update()
    ):
        old.state, old.ciphertext = "EXPIRED", None
    pending = (
        db.scalar(
            select(func.count())
            .select_from(MailDelivery)
            .where(MailDelivery.user_id == user.id, MailDelivery.state.in_(["QUEUED", "SENDING"]))
        )
        or 0
    )
    if pending >= 5:
        return False  # Keep the same generic HTTP response for ineligible accounts.
    row = MailDelivery(
        id=uuid4(),
        user_id=user.id,
        purpose=purpose,
        operation_key=operation,
        nonce=os.urandom(12),
        expires_at=issued.expires_at,
    )
    row.ciphertext = _cipher(settings).encrypt(
        row.nonce,
        json.dumps(
            {
                "recipient": user.email,
                "token": raw,
            }
        ).encode(),
        _aad(row),
    )
    db.add(row)
    db.flush()
    return True


def enqueue_receipt(db: Session, settings: Settings, order_id: UUID) -> bool:
    """Future receipt hook. Reads a settled order; cannot grant credits or accept payment."""
    from zoclip.billing.models import BillingOrder

    order = db.get(BillingOrder, order_id)
    if not order or order.state != "PAID" or not order.grant_id or not order.paid_at:
        raise ValueError("A settled purchase is required")
    user = db.scalar(select(User).where(User.id == order.user_id).with_for_update())
    if settings.email_mode != "smtp" or not user or user.status != "active" or not user.verified:
        return False
    operation = f"receipt:{order.id}"
    if db.scalar(select(MailDelivery.id).where(MailDelivery.operation_key == operation)):
        return True
    row = MailDelivery(
        id=uuid4(),
        user_id=user.id,
        purpose="purchase-receipt",
        operation_key=operation,
        nonce=os.urandom(12),
        expires_at=utcnow() + timedelta(days=7),
    )
    row.ciphertext = _cipher(settings).encrypt(
        row.nonce,
        json.dumps(
            {
                "recipient": user.email,
                "order_id": str(order.id),
                "amount_paisa": order.amount_paisa,
                "credits": order.credits,
            }
        ).encode(),
        _aad(row),
    )
    db.add(row)
    db.flush()
    return True


def deliver_one(factory: sessionmaker, settings: Settings) -> bool:
    if settings.email_mode != "smtp":
        return False
    now = utcnow()
    with factory() as db:
        row = db.scalar(
            select(MailDelivery)
            .where(
                or_(
                    (MailDelivery.state == "QUEUED") & (MailDelivery.due_at <= now),
                    (MailDelivery.state == "SENDING") & (MailDelivery.lease_until <= now),
                )
            )
            .order_by(MailDelivery.due_at, MailDelivery.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return False
        if row.expires_at <= now or row.attempts >= 3:
            row.state = "EXPIRED" if row.expires_at <= now else "FAILED"
            row.ciphertext, row.lease_until, row.lease_token = None, None, None
            db.commit()
            return True
        row.state, row.attempts = "SENDING", row.attempts + 1
        row.lease_token, row.lease_until = uuid4(), now + timedelta(minutes=3)
        identity, lease = row.id, row.lease_token
        db.commit()  # Persist the attempt before any network IO.
    with factory() as db:
        # Retain this row lock during IO: even a slow sender cannot overlap a reclaim.
        row = db.scalar(select(MailDelivery).where(MailDelivery.id == identity).with_for_update())
        if not row or row.state != "SENDING" or row.lease_token != lease:
            return True
        try:
            if row.expires_at <= utcnow():
                raise ValueError("Payload expired")
            if not row.ciphertext:
                raise ValueError("Payload unavailable")
            payload = json.loads(_cipher(settings).decrypt(row.nonce, row.ciphertext, _aad(row)))
            user = db.get(User, row.user_id)
            if not user or user.status != "active" or user.email != payload["recipient"]:
                raise ValueError("Account unavailable")
            if row.purpose != "purchase-receipt":
                model = (
                    EmailVerificationToken if row.purpose == "verify-email" else PasswordResetToken
                )
                issued = db.scalar(
                    select(model).where(
                        model.user_id == row.user_id,
                        model.token_hash == digest(payload["token"]),
                        model.consumed_at.is_(None),
                        model.expires_at > utcnow(),
                    )
                )
                if not issued:
                    raise ValueError("Token unavailable")
            else:
                from zoclip.billing.models import BillingOrder

                order = db.get(BillingOrder, UUID(payload["order_id"]))
                if (
                    not order
                    or order.state != "PAID"
                    or order.user_id != user.id
                    or not order.grant_id
                ):
                    raise ValueError("Settled purchase unavailable")
            sender = SMTPEmail(
                settings.model_copy(
                    update={"smtp_timeout_seconds": min(settings.smtp_timeout_seconds, 10)}
                )
            )
            if row.purpose == "purchase-receipt":
                sender.send_receipt(
                    payload["recipient"],
                    payload["order_id"],
                    payload["amount_paisa"],
                    payload["credits"],
                )
            else:
                sender.send(payload["recipient"], row.purpose, payload["token"])
            row.state, row.ciphertext, row.failure_code = "SENT", None, None
        except ApiError:
            row.failure_code = "email_delivery_failed"
            row.state = "FAILED" if row.attempts >= 3 else "QUEUED"
            row.due_at = utcnow() + timedelta(seconds=60 if row.attempts == 1 else 300)
            if row.state == "FAILED":
                row.ciphertext = None
        except Exception:
            # Includes a missing/rotated key, tampering, stale token or disabled user.
            # Never log raw exceptions containing recipient, credentials or tokens.
            row.state, row.ciphertext, row.failure_code = "FAILED", None, "email_payload_invalid"
        row.lease_until, row.lease_token = None, None
        db.commit()
    return True


def enqueue_recent_receipts(db: Session, settings: Settings) -> None:
    """Read-only billing observer. Outbox writes never mutate financial records."""
    if settings.email_mode != "smtp":
        return
    from zoclip.billing.models import BillingOrder

    order_ids = list(
        db.scalars(
            select(BillingOrder.id)
            .where(
                BillingOrder.state == "PAID",
                BillingOrder.paid_at >= utcnow() - timedelta(days=7),
                ~select(MailDelivery.id)
                .where(MailDelivery.operation_key == "receipt:" + BillingOrder.id.cast(String))
                .exists(),
            )
            .order_by(BillingOrder.paid_at)
            .limit(10)
        )
    )
    for order_id in order_ids:
        enqueue_receipt(db, settings, order_id)


def cleanup_mail(db: Session) -> None:
    now = utcnow()
    rows = list(
        db.scalars(
            select(MailDelivery)
            .where(
                MailDelivery.expires_at <= now,
                MailDelivery.ciphertext.is_not(None),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    )
    for row in rows:
        row.state, row.ciphertext, row.lease_until, row.lease_token = "EXPIRED", None, None, None
    ids = list(
        db.scalars(
            select(MailDelivery.id)
            .where(
                MailDelivery.ciphertext.is_(None),
                MailDelivery.expires_at < now - timedelta(days=7),
            )
            .limit(100)
        )
    )
    if ids:
        db.execute(delete(MailDelivery).where(MailDelivery.id.in_(ids)))
