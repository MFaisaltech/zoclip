from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class User(IdentityMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('customer', 'admin')", name="role"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        CheckConstraint("email = lower(email)", name="normalized_email"),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    verified: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    role: Mapped[str] = mapped_column(String(20), default="customer")


class AuthSession(IdentityMixin, Base):
    __tablename__ = "sessions"
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TokenMixin(IdentityMixin):
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerificationToken(TokenMixin, Base):
    __tablename__ = "email_verification_tokens"


class PasswordResetToken(TokenMixin, Base):
    __tablename__ = "password_reset_tokens"


class OAuthIdentity(IdentityMixin, Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),
        UniqueConstraint("provider", "user_id", name="uq_oauth_provider_user"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(255))
    verified_email: Mapped[str] = mapped_column(String(320))


class OAuthFlow(IdentityMixin, Base):
    __tablename__ = "oauth_flows"
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(128))
    code_verifier: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdentityMixin, Base):
    __tablename__ = "admin_audit_logs"
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[UUID | None]
    request_id: Mapped[str] = mapped_column(String(36))
