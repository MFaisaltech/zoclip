"""Revoke through source/job state first; remove only files without a live writer."""

import os
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from zoclip.core.db import utcnow
from zoclip.media import service as media
from zoclip.media.models import Job, SourceVideo, StorageObject
from zoclip.media.storage import LocalStorage
from zoclip.rendering.models import Clip, ClipRevision, RenderOutput


def erase_revisions(db: Session, video_id: UUID) -> None:
    for clip in db.scalars(select(Clip).where(Clip.video_id == video_id)):
        clip.suggestion_id = None
        for revision in db.scalars(select(ClipRevision).where(ClipRevision.clip_id == clip.id)):
            db.delete(revision)
    db.flush()


def cleanup_outputs(factory: sessionmaker, storage: LocalStorage) -> None:
    with factory() as db:
        ids = list(
            db.scalars(
                select(RenderOutput.id)
                .join(Job)
                .join(SourceVideo)
                .where(
                    RenderOutput.state != "DELETED",
                    (SourceVideo.state.in_({"DELETED", "FAILED"}))
                    | (SourceVideo.expires_at <= utcnow())
                    | Job.state.in_({"FAILED", "CANCELED"}),
                )
                .limit(100)
            )
        )
    for output_id in ids:
        with factory() as db:
            initial = db.get(RenderOutput, output_id)
            media.mutex(db, initial.user_id, cleanup=True)
            output = db.get(RenderOutput, output_id, with_for_update=True)
            job = media.required(db, Job, output.job_id)
            if job.state in media.ACTIVE:
                media.cancel_job(db, job.user_id, job.id)
            if job.state in {"RUNNING", "CANCEL_REQUESTED"}:
                db.commit()
                continue
            storage.delete(output.object_id)
            obj = media.required(db, StorageObject, output.object_id)
            obj.deleted, obj.reserved_bytes, obj.materialized_bytes = True, 0, 0
            output.state, output.metadata_json = "DELETED", {}
            db.commit()
    # A killed process may leave its generated ASS directory. Never follow symlinks.
    with os.scandir(storage.root) as entries:
        for _, entry in zip(range(1000), entries, strict=False):
            if (
                entry.name.startswith("render-")
                and entry.is_dir(follow_symlinks=False)
                and time.time() - entry.stat(follow_symlinks=False).st_mtime > 3600
            ):
                try:
                    with os.scandir(entry.path) as files:
                        for file in files:
                            if file.name == "captions.ass" and file.is_file(follow_symlinks=False):
                                os.unlink(file.path)
                    os.rmdir(entry.path)
                except (FileNotFoundError, OSError):
                    pass
