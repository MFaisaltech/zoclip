from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from zoclip.auth.dependencies import (
    DB,
    AdminUser,
    CsrfSession,
    CurrentSession,
    CurrentUser,
    owned_resource,
)
from zoclip.auth.models import (
    AuditLog,
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    User,
)
from zoclip.auth.schemas import (
    AuditPage,
    AuditView,
    Credentials,
    CsrfResponse,
    EmailInput,
    InviteInput,
    LoginResponse,
    Me,
    Message,
    ResetInput,
    SessionView,
    TokenInput,
)
from zoclip.auth.service import (
    audit,
    consume_email_token,
    issue_email_token,
    lock_active_user,
    new_session,
)
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.rate_limit import rate_limit
from zoclip.core.security import (
    COOKIE_NAME,
    PASSWORD_HASHER,
    digest,
    hash_password,
    token,
    verify_password,
)
from zoclip.ops.staging_accounts import redeem

router = APIRouter(prefix="/api/v1", tags=["authentication"])
GENERIC_MESSAGE = Message(message="If eligible, check your email for the next step.")


@router.post("/auth/invite/accept", response_model=Message)
def accept_invite(data: InviteInput, request: Request, db: DB, csrf: CsrfSession) -> Message:
    if not request.app.state.settings.private_staging:
        raise ApiError(404, "not_found", "Invite redemption is unavailable.")
    rate_limit(request, "staging-invite")
    hashed = hash_password(data.password)
    try:
        redeem(db, request.app.state.settings, data.token, hashed)
    except ValueError as exc:
        raise ApiError(400, "invalid_token", "Invite unavailable.") from exc
    db.commit()
    return Message(message="Invite accepted. Sign in with your new password.")


@router.get("/auth/csrf", response_model=CsrfResponse)
def csrf(request: Request, response: Response, db: DB, session: CurrentSession) -> CsrfResponse:
    rate_limit(request, "csrf")
    if session:
        raw = token()
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == session.id, AuthSession.revoked_at.is_(None))
            .values(csrf_hash=digest(raw))
        )
    else:
        raw = new_session(db, request, response, None)
    db.commit()
    return CsrfResponse(csrf_token=raw)


@router.post("/auth/register", response_model=Message, status_code=202)
def register(data: Credentials, request: Request, db: DB, csrf: CsrfSession) -> Message:
    settings = request.app.state.settings
    if settings.app_env == "production" and not settings.registration_enabled:
        raise ApiError(503, "registration_disabled", "Public registration is disabled.")
    rate_limit(request, "register", str(data.email))
    email_sender = request.app.state.email_sender
    email_sender.ensure_available()
    hashed = hash_password(data.password)
    user = db.scalar(select(User).where(User.email == str(data.email)).with_for_update())
    if user is None:
        user = User(email=str(data.email), password_hash=hashed)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return GENERIC_MESSAGE
    if user.verified or user.status != "active":
        return GENERIC_MESSAGE
    raw = issue_email_token(db, user, EmailVerificationToken)
    audit(db, request, "auth.verification_requested", target=user.id)
    db.commit()
    email_sender.send(user.email, "verify-email", raw)
    return GENERIC_MESSAGE


@router.post("/auth/verify-email", response_model=Message)
def verify_email(data: TokenInput, request: Request, db: DB, csrf: CsrfSession) -> Message:
    rate_limit(request, "verify")
    user = consume_email_token(db, data.token, EmailVerificationToken)
    user.verified = True
    audit(db, request, "auth.email_verified", actor=user.id, target=user.id)
    db.commit()
    return Message(message="Email verified. You may log in.")


@router.post("/auth/login", response_model=LoginResponse)
def login(
    data: Credentials, request: Request, response: Response, db: DB, csrf: CsrfSession
) -> LoginResponse:
    rate_limit(request, "login", str(data.email))
    user = db.scalar(select(User).where(User.email == str(data.email)).with_for_update())
    valid = verify_password(user.password_hash if user else None, data.password)
    if not valid or not user or not user.verified or user.status != "active":
        audit(db, request, "auth.login_failed")
        db.commit()
        raise ApiError(401, "invalid_credentials", "Invalid credentials or account unavailable.")
    if user.password_hash and PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    # Serialize rotation after the user lock so password reset and login cannot race.
    previous = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == csrf.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not previous or previous.revoked_at or previous.expires_at <= utcnow():
        raise ApiError(401, "session_expired", "Restart login.")
    new_csrf = new_session(db, request, response, user.id, previous)
    audit(db, request, "auth.login", actor=user.id, target=user.id)
    db.commit()
    return LoginResponse(user=Me.model_validate(user), csrf_token=new_csrf)


@router.post("/auth/logout", response_model=Message)
def logout(request: Request, response: Response, db: DB, csrf: CsrfSession) -> Message:
    db.execute(update(AuthSession).where(AuthSession.id == csrf.id).values(revoked_at=utcnow()))
    audit(db, request, "auth.logout", actor=csrf.user_id, target=csrf.user_id)
    db.commit()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return Message(message="Logged out.")


@router.post("/auth/session/rotate", response_model=CsrfResponse)
def rotate(
    request: Request, response: Response, db: DB, user: CurrentUser, csrf: CsrfSession
) -> CsrfResponse:
    rate_limit(request, "rotate")
    lock_active_user(db, user.id)
    previous = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == csrf.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not previous or previous.revoked_at or previous.expires_at <= utcnow():
        raise ApiError(401, "session_expired", "Log in again.")
    value = new_session(db, request, response, user.id, previous)
    audit(db, request, "auth.session_rotated", actor=user.id, target=user.id)
    db.commit()
    return CsrfResponse(csrf_token=value)


@router.post("/auth/password/forgot", response_model=Message, status_code=202)
def forgot(data: EmailInput, request: Request, db: DB, csrf: CsrfSession) -> Message:
    rate_limit(request, "forgot", str(data.email))
    request.app.state.email_sender.ensure_available()
    user = db.scalar(select(User).where(User.email == str(data.email)).with_for_update())
    # Always perform comparable password work, whether or not an account is eligible.
    hash_password(token())
    raw = None
    if user and user.status == "active" and user.verified and user.password_hash:
        raw = issue_email_token(db, user, PasswordResetToken)
        audit(db, request, "auth.reset_requested", target=user.id)
    db.commit()
    if raw and user:
        request.app.state.email_sender.send(user.email, "password-reset", raw)
    return GENERIC_MESSAGE


@router.post("/auth/password/reset", response_model=Message)
def reset(data: ResetInput, request: Request, db: DB, csrf: CsrfSession) -> Message:
    rate_limit(request, "reset")
    hashed = hash_password(data.password)
    user = consume_email_token(db, data.token, PasswordResetToken)
    user.password_hash = hashed
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.consumed_at.is_(None))
        .values(consumed_at=utcnow())
    )
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit(db, request, "auth.password_reset", actor=user.id, target=user.id)
    db.commit()
    return Message(message="Password reset. Log in again.")


@router.get("/me", response_model=Me)
def me(user: CurrentUser) -> Me:
    return Me.model_validate(user)


@router.get("/me/sessions/{session_id}", response_model=SessionView)
def own_session(session_id: UUID, user: CurrentUser, db: DB) -> SessionView:
    return SessionView.model_validate(owned_resource(db, AuthSession, session_id, user.id))


@router.get("/admin/audit-logs", response_model=AuditPage, tags=["admin"])
def audit_logs(
    request: Request,
    db: DB,
    user: AdminUser,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: UUID | None = None,
) -> AuditPage:
    query = select(AuditLog).order_by(AuditLog.id).limit(limit + 1)
    if cursor:
        query = query.where(AuditLog.id > cursor)
    rows = list(db.scalars(query))
    result = AuditPage(
        items=[AuditView.model_validate(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    audit(db, request, "admin.audit_read", actor=user.id)
    db.commit()
    return result
