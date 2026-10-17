"""Bounded transactional outbox. Token/recipient payloads are authenticated ciphertext."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin, utcnow


class MailDelivery(IdentityMixin, Base):
    __tablename__ = "mail_deliveries"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('verify-email','password-reset','purchase-receipt')", name="purpose"
        ),
        CheckConstraint("state IN ('QUEUED','SENDING','SENT','FAILED','EXPIRED')", name="state"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))
    operation_key: Mapped[str] = mapped_column(String(128), unique=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12), unique=True)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(12), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    failure_code: Mapped[str | None] = mapped_column(String(40))
