from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from zoclip.core.db import Base, IdentityMixin


class StoragePool(Base):
    __tablename__ = "storage_pool"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True)


class Project(IdentityMixin, Base):
    __tablename__ = "projects"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)


class StorageObject(IdentityMixin, Base):
    __tablename__ = "storage_objects"
    __table_args__ = (
        CheckConstraint(
            "reserved_bytes >= 0 AND materialized_bytes >= 0 "
            "AND materialized_bytes <= reserved_bytes",
            name="capacity",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    materialized_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted: Mapped[bool] = mapped_column(default=False)


class SourceVideo(IdentityMixin, Base):
    __tablename__ = "source_videos"
    __table_args__ = (
        CheckConstraint(
            "state IN ('UPLOADING','IMPORTING','VALIDATING','READY','FAILED','DELETED')",
            name="state",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), unique=True)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("storage_objects.id"), unique=True)
    state: Mapped[str] = mapped_column(String(24))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UploadSession(IdentityMixin, Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key"),
        CheckConstraint("expected_bytes > 0 AND part_bytes > 0", name="sizes"),
        CheckConstraint(
            "state IN ('OPEN','FINALIZING','COMPLETE','CANCELED','FAILED')", name="state"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), unique=True)
    operation_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    expected_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    part_bytes: Mapped[int]
    state: Mapped[str] = mapped_column(String(24), default="OPEN")
    write_token: Mapped[UUID | None]
    write_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UploadPart(IdentityMixin, Base):
    __tablename__ = "upload_parts"
    __table_args__ = (
        UniqueConstraint("upload_id", "number"),
        CheckConstraint("number >= 0 AND size > 0", name="sizes"),
    )
    upload_id: Mapped[UUID] = mapped_column(ForeignKey("upload_sessions.id"), index=True)
    number: Mapped[int]
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))


class Job(IdentityMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key"),
        CheckConstraint("kind IN ('VALIDATE','IMPORT','PROCESS')", name="kind"),
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','WAITING_ENGINE','CANCEL_REQUESTED',"
            "'CANCELED','FAILED','COMPLETED')",
            name="state",
        ),
        CheckConstraint("attempts >= 0 AND generation >= 0", name="attempts"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    video_id: Mapped[UUID] = mapped_column(ForeignKey("source_videos.id"), index=True)
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credit_reservations.id"), unique=True
    )
    operation_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24), default="QUEUED", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # private; never serialized
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    generation: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def stage(self) -> str:
        if self.state == "RUNNING":
            return {"VALIDATE": "VALIDATING", "IMPORT": "IMPORTING", "PROCESS": "ENGINE_PENDING"}[
                self.kind
            ]
        if self.state == "COMPLETED" and self.kind != "PROCESS":
            return "SOURCE_READY"
        return self.state

    @property
    def progress_percent(self) -> int | None:
        # Only the completed ingestion milestone has a measurable percentage.
        return 100 if self.state == "COMPLETED" and self.kind != "PROCESS" else None

    @property
    def estimated_credits(self) -> int | None:
        # Persist the accepted reservation amount, never recompute from current prices.
        return self.checkpoint.get("estimated_credits") if self.kind == "PROCESS" else 0


class JobEvent(IdentityMixin, Base):
    __tablename__ = "job_events"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[str] = mapped_column(String(24))
    code: Mapped[str | None] = mapped_column(String(64))


class Outbox(IdentityMixin, Base):
    __tablename__ = "job_outbox"
    __table_args__ = (UniqueConstraint("job_id", "generation"),)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    generation: Mapped[int]
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_token: Mapped[UUID | None]
    dispatch_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
