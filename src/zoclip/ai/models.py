from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class AIRequest(IdentityMixin, Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "cache_key", "number"),
        CheckConstraint("number BETWEEN 1 AND 3", name="number"),
        CheckConstraint("provider IN ('deepgram','gemini','whisper')", name="provider"),
        CheckConstraint(
            "state IN ('ADMITTED','RESPONDED','RECORDED','REJECTED','UNKNOWN')", name="state"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(128))
    cache_key: Mapped[str] = mapped_column(String(64))
    number: Mapped[int]
    state: Mapped[str] = mapped_column(String(20), default="ADMITTED")
    attempt_ids: Mapped[list] = mapped_column(JSON)
    response: Mapped[dict | None] = mapped_column(JSON)
    response_hash: Mapped[str | None] = mapped_column(String(64))


class Transcript(IdentityMixin, Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("user_id", "cache_key"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("ai_requests.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(20))
    audio_sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class ClipSuggestion(IdentityMixin, Base):
    __tablename__ = "clip_suggestions"
    __table_args__ = (UniqueConstraint("job_id", "rank"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    transcript_id: Mapped[UUID] = mapped_column(ForeignKey("transcripts.id"), index=True)
    rank: Mapped[int]
    data: Mapped[dict] = mapped_column(JSON)
