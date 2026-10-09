import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.orm import Session

from zoclip.auth.models import AuthSession, User
from zoclip.core.db import get_db, utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import COOKIE_NAME, digest

DB = Annotated[Session, Depends(get_db)]
session_cookie = APIKeyCookie(name=COOKIE_NAME, auto_error=False)


def optional_session(
    db: DB, raw: Annotated[str | None, Depends(session_cookie)]
) -> AuthSession | None:
    if not raw or len(raw) > 128:
        return None
    return db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == digest(raw),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )


CurrentSession = Annotated[AuthSession | None, Depends(optional_session)]


def require_csrf(
    request: Request,
    session: CurrentSession,
    origin: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> AuthSession:
    settings = request.app.state.settings
    if origin not in {settings.public_app_url, settings.api_public_url}:
        raise ApiError(403, "csrf_failed", "A permitted Origin and CSRF token are required.")
    supplied = x_csrf_token or ""
    if (
        not session
        or not supplied
        or len(supplied) > 128
        or not secrets.compare_digest(session.csrf_hash, digest(supplied))
    ):
        raise ApiError(403, "csrf_failed", "A permitted Origin and CSRF token are required.")
    return session


CsrfSession = Annotated[AuthSession, Depends(require_csrf)]


def current_user(session: CurrentSession, db: DB) -> User:
    user = db.get(User, session.user_id) if session and session.user_id else None
    if not user or user.status != "active" or not user.verified:
        raise ApiError(401, "authentication_required", "A verified active account is required.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Staff permission required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def owned_resource(db: Session, model: Any, resource_id: UUID, owner_id: UUID) -> Any:
    """Owner is part of the query, never an unchecked client supplied owner ID."""
    resource = db.scalar(select(model).where(model.id == resource_id, model.user_id == owner_id))
    if resource is None:
        raise ApiError(404, "not_found", "Resource not found.")
    return resource
