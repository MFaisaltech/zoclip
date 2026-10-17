"""Operator-approved private-staging invites, separate from acceptance bootstrap/guards."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from zoclip.auth.models import AuditLog, AuthSession, StagingInvite, User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import digest, token
from zoclip.credits.models import SystemLimits


class InviteApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    purpose: Literal["first_admin", "reviewer"]
    email: EmailStr = Field(max_length=320)
    actor_id: UUID | None = None
    operator: str = Field(min_length=3, max_length=200)
    identity_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: datetime
    expires_at: datetime

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.lower()


def target_hash(settings: Settings) -> str:
    db = make_url(settings.database_url.get_secret_value())
    target = {
        "host": db.host,
        "port": db.port or 5432,
        "database": db.database,
        "connection_options": sorted(db.query.items()),
        "app": settings.public_app_url,
        "api": settings.api_public_url,
        "site": settings.staging_site_domain,
        "invite_epoch": str(settings.staging_invite_epoch),
    }
    return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()


def check_approval(settings: Settings, approval: InviteApproval) -> None:
    if (
        not settings.private_staging
        or settings.app_env != "production"
        or settings.staging_invite_epoch is None
    ):
        raise ValueError("Production private-staging settings required")
    now = utcnow()
    if (
        approval.approved_at.tzinfo is None
        or approval.expires_at.tzinfo is None
        or not now - timedelta(minutes=15) <= approval.approved_at <= now
        or not now < approval.expires_at <= approval.approved_at + timedelta(hours=1)
    ):
        raise ValueError("Fresh approval and a maximum one-hour invite lifetime required")
    if approval.target_sha256 != target_hash(settings):
        raise ValueError("Approval does not match this database and exact browser origins")
    if (approval.purpose == "first_admin") != (approval.actor_id is None):
        raise ValueError("First-admin owner approval or an existing admin actor required")


def fence(db: Session, settings: Settings) -> None:
    if (
        not settings.private_staging
        or settings.app_env != "production"
        or settings.staging_invite_epoch is None
    ):
        raise ValueError("Production private-staging settings required")
    system = db.scalar(select(SystemLimits).where(SystemLimits.id == 1).with_for_update())
    if system is None or not system.breaker:
        raise ValueError("Existing spending breaker must stay true; never auto-repaired")


def event(db: Session, invite: StagingInvite, action: str, actor: UUID | None) -> None:
    db.add(
        AuditLog(actor_id=actor, target_id=invite.user_id, action=action, request_id=str(invite.id))
    )


def require_actor(db: Session, actor_id: UUID | None) -> None:
    actor = (
        db.scalar(
            select(User)
            .where(User.id == actor_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if actor_id
        else None
    )
    if not actor or not actor.verified or actor.status != "active" or actor.role != "admin":
        raise ValueError("Active verified admin actor required")


def first_admin_allowed(db: Session, *, ignore: UUID | None = None) -> None:
    if db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or db.scalar(
        select(AuditLog.id).where(AuditLog.action == "staging.first_admin_activated").limit(1)
    ):
        raise ValueError("First-admin bootstrap permanently closed after first activation")
    pending = select(StagingInvite.id).where(
        StagingInvite.purpose == "first_admin",
        StagingInvite.consumed_at.is_(None),
        StagingInvite.revoked_at.is_(None),
        StagingInvite.expires_at > utcnow(),
    )
    if ignore:
        pending = pending.where(StagingInvite.id != ignore)
    if db.scalar(pending.limit(1)):
        raise ValueError("A first-admin invite is already outstanding")


def issue(
    db: Session, settings: Settings, approval: InviteApproval, approval_hash: str
) -> tuple[StagingInvite, str]:
    check_approval(settings, approval)
    if not re.fullmatch(r"[a-f0-9]{64}", approval_hash):
        raise ValueError("Exact approval SHA-256 required")
    fence(db, settings)  # Global serialization, including competing first-admin/reissue/revoke.
    if db.get(StagingInvite, approval.operation_id):
        raise ValueError("Operation already issued; inspect retained token, never regenerate it")
    if approval.purpose == "first_admin":
        first_admin_allowed(db)
    else:
        require_actor(db, approval.actor_id)
    user = db.scalar(select(User).where(User.email == str(approval.email)).with_for_update())
    if user:
        previous = list(db.scalars(select(StagingInvite).where(StagingInvite.user_id == user.id)))
        if (
            user.verified
            or user.password_hash
            or user.role != "customer"
            or user.status != "active"
            or not previous
            or any(
                p.consumed_at
                or p.purpose != approval.purpose
                or (not p.revoked_at and p.expires_at > utcnow())
                for p in previous
            )
        ):
            raise ValueError(
                "Existing account cannot be overwritten; revoke/expire a pending invite"
            )
        for old in previous:
            if not old.revoked_at:
                old.revoked_at = utcnow()
                event(db, old, "staging.invite_expired_replaced", approval.actor_id)
    else:
        user = User(email=str(approval.email), verified=False, role="customer", status="active")
        db.add(user)
        db.flush()
    raw = token()
    invite = StagingInvite(
        id=approval.operation_id,
        user_id=user.id,
        actor_id=approval.actor_id,
        purpose=approval.purpose,
        token_hash=digest(raw),
        approval_hash=approval_hash,
        target_hash=target_hash(settings),
        expires_at=approval.expires_at,
    )
    db.add(invite)
    event(db, invite, "staging.invite_issued", approval.actor_id)
    event(db, invite, "staging.approve:" + approval_hash, approval.actor_id)
    db.flush()
    return (
        invite,
        raw,
    )  # Caller alone delivers privately and commits; never log/return through HTTP.


def redeem(db: Session, settings: Settings, raw: str, password_hash: str) -> None:
    fence(db, settings)
    invite = db.scalar(
        select(StagingInvite)
        .where(StagingInvite.token_hash == digest(raw))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not invite
        or invite.consumed_at
        or invite.revoked_at
        or invite.expires_at <= utcnow()
        or invite.target_hash != target_hash(settings)
    ):
        raise ApiError(400, "invalid_token", "Invite invalid, expired or already used.")
    user = db.scalar(
        select(User)
        .where(User.id == invite.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or user.status != "active"
        or user.verified
        or user.password_hash
        or user.role != "customer"
    ):
        raise ApiError(400, "invalid_token", "Invite unavailable.")
    if invite.purpose == "first_admin":
        first_admin_allowed(db, ignore=invite.id)
        user.role = "admin"
        event(db, invite, "staging.first_admin_activated", None)
    else:
        require_actor(
            db, invite.actor_id
        )  # Revoked/disabled issuer invalidates outstanding invites.
    user.password_hash, user.verified = password_hash, True
    invite.consumed_at = utcnow()
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    event(db, invite, "staging.invite_redeemed", user.id)
    db.flush()  # No auto-login or credit grants. Caller commits atomically.


def revoke(db: Session, settings: Settings, operation_id: UUID, actor_id: UUID | None) -> None:
    fence(db, settings)
    invite = db.get(StagingInvite, operation_id)
    if not invite or invite.consumed_at or invite.revoked_at:
        raise ValueError("Only an outstanding invite can be revoked")
    # Revocation grants no authority and may retire a restored/previous-epoch invite.
    if invite.purpose == "first_admin" and actor_id is None:
        first_admin_allowed(db, ignore=invite.id)
    else:
        require_actor(db, actor_id)
    invite.revoked_at = utcnow()
    event(db, invite, "staging.invite_revoked", actor_id)
    db.flush()


def revoke_reviewer(db: Session, settings: Settings, operation_id: UUID, actor_id: UUID) -> None:
    """Revoke only a provisioned staging customer, never the first admin or ordinary users."""
    fence(db, settings)
    require_actor(db, actor_id)
    invite = db.get(StagingInvite, operation_id)
    if not invite or invite.purpose != "reviewer" or not invite.consumed_at:
        raise ValueError("Consumed staging reviewer authorization required")
    user = db.scalar(
        select(User)
        .where(User.id == invite.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or user.role != "customer" or user.id == actor_id:
        raise ValueError("Only an authorized staging customer can be revoked")
    if db.scalar(
        select(AuditLog.id).where(
            AuditLog.request_id == str(invite.id), AuditLog.action == "staging.reviewer_revoked"
        )
    ):
        return
    user.status = "disabled"
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    event(db, invite, "staging.reviewer_revoked", actor_id)
    db.flush()
