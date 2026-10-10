from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class Clip(IdentityMixin, Base):
    __tablename__ = "clips"
    __table_args__ = (
        UniqueConstraint("suggestion_id"),
        CheckConstraint("revision > 0", name="revision"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    # Nullable so retention can erase candidate/transcript text independently.
    suggestion_id: Mapped[UUID | None] = mapped_column(ForeignKey("clip_suggestions.id"))
    revision: Mapped[int] = mapped_column(default=1)


class ClipRevision(IdentityMixin, Base):
    __tablename__ = "clip_revisions"
    __table_args__ = (
        UniqueConstraint("clip_id", "number"),
        CheckConstraint("number > 0", name="number"),
    )
    clip_id: Mapped[UUID] = mapped_column(ForeignKey("clips.id"), index=True)
    number: Mapped[int]
    preferences: Mapped[dict] = mapped_column(JSON)


class RenderOutput(IdentityMixin, Base):
    __tablename__ = "render_outputs"
    __table_args__ = (
        UniqueConstraint("clip_id", "revision"),
        CheckConstraint("revision > 0 AND failures >= 0", name="counts"),
        CheckConstraint("state IN ('PENDING','COMPLETE','FAILED','DELETED')", name="state"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    clip_id: Mapped[UUID] = mapped_column(ForeignKey("clips.id"), index=True)
    revision: Mapped[int]
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("storage_objects.id"), unique=True)
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    failures: Mapped[int] = mapped_column(default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
