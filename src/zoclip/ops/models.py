from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class PrivacyRequest(IdentityMixin, Base):
    __tablename__ = "privacy_erasure_requests"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    payload_hash: Mapped[str] = mapped_column(String(64))
