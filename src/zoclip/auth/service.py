from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from zoclip.auth.models import (
    AuditLog,
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    User,
)
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import COOKIE_NAME, digest, token


def audit(
    db: Session,
    request: Request,
    action: str,
    actor: UUID | None = None,
    target: UUID | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor, action=action, target_id=target, request_id=request.state.request_id
        )
    )


def new_session(
    db: Session,
    request: Request,
    response: Response,
    user_id: UUID | None,
    previous: AuthSession | None = None,
) -> str:
    if previous:
        previous.revoked_at = utcnow()
    raw, csrf = token(), token()
    settings = request.app.state.settings
    ttl = settings.session_ttl_seconds if user_id else settings.anonymous_ttl_seconds
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=digest(raw),
            csrf_hash=digest(csrf),
            expires_at=utcnow() + timedelta(seconds=ttl),
        )
    )
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=ttl,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return csrf


def lock_active_user(db: Session, user_id: UUID) -> User:
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not user.verified or user.status != "active":
        raise ApiError(401, "authentication_required", "Active account required.")
    return user


def issue_email_token(
    db: Session, user: User, model: type[EmailVerificationToken] | type[PasswordResetToken]
) -> str:
    db.execute(
        update(model)
        .where(model.user_id == user.id, model.consumed_at.is_(None))
        .values(consumed_at=utcnow())
    )
    raw = token()
    ttl = 3600 if model is PasswordResetToken else 86400
    db.add(
        model(user_id=user.id, token_hash=digest(raw), expires_at=utcnow() + timedelta(seconds=ttl))
    )
    return raw


def consume_email_token(
    db: Session, raw: str, model: type[EmailVerificationToken] | type[PasswordResetToken]
) -> User:
    table: Any = model
    entry = db.scalar(select(table).where(table.token_hash == digest(raw)))
    if not entry:
        raise ApiError(400, "invalid_token", "Token invalid or expired.")
    user = db.scalar(select(User).where(User.id == entry.user_id).with_for_update())
    entry = db.scalar(
        select(table)
        .where(table.id == entry.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or user.status != "active"
        or not entry
        or entry.consumed_at
        or entry.expires_at <= utcnow()
    ):
        raise ApiError(400, "invalid_token", "Token invalid or expired.")
    entry.consumed_at = utcnow()
    return user
