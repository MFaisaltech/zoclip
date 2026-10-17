"""Operator-only test sponsorship. Never a wallet credit or customer entitlement."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class LiveTest(Base):
    __tablename__ = "isolated_live_test"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "cap_usd = 0.10 AND committed_usd >= 0 AND committed_usd <= cap_usd",
            name="aggregate_cap",
        ),
        CheckConstraint("state IN ('PREPARED','APPROVED','STOPPED','COMPLETED')", name="state"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(unique=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_bytes: Mapped[int]
    duration_ms: Mapped[int]
    cap_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    committed_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=Decimal(0))
    policy: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="PREPARED")
    approval_hash: Mapped[str | None] = mapped_column(String(64))
    approval_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_hashes: Mapped[dict | None] = mapped_column(JSON)


class LiveTestCall(IdentityMixin, Base):
    __tablename__ = "isolated_live_test_calls"
    __table_args__ = (
        CheckConstraint("component IN ('deepgram','gemini','render')", name="component"),
        CheckConstraint("ceiling_usd > 0 AND ceiling_usd <= 0.10", name="ceiling"),
        CheckConstraint("state IN ('HELD','RECORDED','UNKNOWN')", name="state"),
    )
    test_id: Mapped[int] = mapped_column(ForeignKey("isolated_live_test.id"))
    # Only one test can ever exist, so each component is globally single-use.
    component: Mapped[str] = mapped_column(String(16), unique=True)
    ceiling_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    state: Mapped[str] = mapped_column(String(16), default="HELD")
    response: Mapped[dict | None] = mapped_column(JSON)
