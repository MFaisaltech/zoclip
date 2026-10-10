"""Lease-aware retention; financial history and job audit events are retained."""

import os
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from zoclip.ai.models import AIRequest, ClipSuggestion, Transcript
from zoclip.core.db import utcnow
from zoclip.media import service
from zoclip.media.models import Job, SourceVideo, StorageObject, UploadPart, UploadSession
from zoclip.media.storage import LocalStorage


def cleanup(factory: sessionmaker, storage: LocalStorage) -> int:
    now = utcnow()
    with factory() as db:
        ids = list(
            db.scalars(
                select(SourceVideo.id)
                .join(StorageObject, StorageObject.id == SourceVideo.object_id)
                .outerjoin(UploadSession, UploadSession.video_id == SourceVideo.id)
                .where(StorageObject.deleted.is_(False))
                .where(
                    (SourceVideo.expires_at <= now)
                    | SourceVideo.state.in_({"FAILED", "DELETED"})
                    | ((UploadSession.expires_at <= now) & (UploadSession.state == "OPEN"))
                )
                .limit(100)
            )
        )
        waiting = list(
            db.scalars(
                select(Job.id)
                .where(
                    Job.state.in_({"WAITING_ENGINE", "SUGGESTIONS_READY"}),
                    Job.updated_at < now - timedelta(days=1),
                )
                .limit(100)
            )
        )
    for job_id in waiting:
        with factory() as db:
            job = db.get(Job, job_id)
            service.cancel_job(db, job.user_id, job.id)
            db.commit()
    count = 0
    for video_id in ids:
        with factory() as db:
            video = db.get(SourceVideo, video_id)
            service.mutex(db, video.user_id, cleanup=True)
            obj = db.get(StorageObject, video.object_id)
            if obj.deleted:
                continue
            upload = db.scalar(select(UploadSession).where(UploadSession.video_id == video.id))
            if upload and upload.write_until and upload.write_until > now:
                continue
            service.delete_video(db, video.user_id, video.id)
            db.flush()
            if db.scalar(
                select(Job.id)
                .where(Job.video_id == video.id, Job.state.in_(service.ACTIVE))
                .limit(1)
            ):
                db.commit()  # Cancellation request persisted; live worker still owns disk.
                continue
            from zoclip.ai.worker import finalize_pending

            for job in db.scalars(select(Job).where(Job.video_id == video.id)):
                finalize_pending(db, job, storage)
            storage.delete(obj.id)
            for suggestion in db.scalars(
                select(ClipSuggestion).where(ClipSuggestion.video_id == video.id)
            ):
                db.delete(suggestion)
            db.flush()
            for transcript in db.scalars(select(Transcript).where(Transcript.video_id == video.id)):
                # Identical owner/source reuse can link another job to this transcript.
                for suggestion in db.scalars(
                    select(ClipSuggestion).where(ClipSuggestion.transcript_id == transcript.id)
                ):
                    db.delete(suggestion)
                db.flush()
                db.delete(transcript)
            for request in db.scalars(select(AIRequest).where(AIRequest.video_id == video.id)):
                storage.delete(request.id)
                request.response = None  # Retain cost references/hashes, remove private text.
            for job in db.scalars(select(Job).where(Job.video_id == video.id)):
                job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "candidates"}
            if upload:
                for part in db.scalars(select(UploadPart).where(UploadPart.upload_id == upload.id)):
                    storage.delete(part.id)
            obj.deleted, obj.reserved_bytes, obj.materialized_bytes = True, 0, 0
            db.commit()
            count += 1
    # Completed sources no longer need upload parts. They may have survived a crash.
    with factory() as db:
        parts = list(
            db.scalars(
                select(UploadPart)
                .join(UploadSession, UploadSession.id == UploadPart.upload_id)
                .where(UploadSession.state == "COMPLETE")
                .limit(1000)
            )
        )
        for part in parts:
            storage.delete(part.id)
            db.delete(part)  # Temporary part receipts, never financial/job audit history.
        db.commit()
    # Bounded streaming directory cursor, not an ever-growing in-memory history set.
    if storage.sweep is None:
        storage.sweep = os.scandir(storage.root)
    with factory() as db:
        for _ in range(1000):
            try:
                path = next(storage.sweep)
            except StopIteration:
                storage.sweep.close()
                storage.sweep = None
                break
            if path.is_symlink() or not path.is_file(follow_symlinks=False) or len(path.name) != 32:
                continue
            try:
                key = UUID(hex=path.name)
                old = time.time() - path.stat(follow_symlinks=False).st_mtime > 3600
            except (ValueError, FileNotFoundError):
                continue
            if (
                old
                and not db.scalar(
                    select(StorageObject.id).where(
                        StorageObject.id == key, StorageObject.deleted.is_(False)
                    )
                )
                and not db.get(UploadPart, key)
                and not db.get(AIRequest, key)
            ):
                storage.delete(key)
    return count
