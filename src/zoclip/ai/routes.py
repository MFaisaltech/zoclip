from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from zoclip.ai.models import ClipSuggestion, Transcript
from zoclip.ai.schemas import SuggestionsView, SuggestionView, TranscriptData, TranscriptView
from zoclip.auth.dependencies import CurrentUser
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.media import service
from zoclip.media.models import Job, SourceVideo
from zoclip.media.routes import DB

router = APIRouter(prefix="/api/v1", tags=["ai"])


def retained(db: DB, owner: UUID, video_id: UUID) -> None:
    # Same revocation boundary as private media; no stale preloaded authorization.
    service.mutex(db, owner)
    video = service.owned(db, SourceVideo, owner, video_id, lock=True)
    if video.state != "READY" or video.expires_at <= utcnow():
        raise ApiError(404, "not_found", "Retained source not found.")


@router.get("/videos/{video_id}/transcript", response_model=TranscriptView)
def get_transcript(
    video_id: UUID, db: DB, user: CurrentUser, job_id: UUID | None = None
) -> TranscriptView:
    retained(db, user.id, video_id)
    jobs = select(Job).where(
        Job.user_id == user.id, Job.video_id == video_id, Job.kind == "PROCESS"
    )
    if job_id:
        jobs = jobs.where(Job.id == job_id)
    job = db.scalar(jobs.order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    if not job or not job.checkpoint.get("transcript_id"):
        raise ApiError(404, "transcript_unavailable", "Transcript is not available for this job.")
    row = service.owned(db, Transcript, user.id, UUID(job.checkpoint["transcript_id"]))
    result = TranscriptView(
        id=row.id,
        video_id=video_id,
        job_id=job.id,
        model=row.model,
        language=row.language,
        created_at=row.created_at,
        data=TranscriptData.model_validate(row.data),
    )
    db.commit()
    return result


@router.get("/videos/{video_id}/suggestions", response_model=SuggestionsView)
def get_suggestions(
    video_id: UUID,
    db: DB,
    user: CurrentUser,
    job_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=20),
) -> SuggestionsView:
    retained(db, user.id, video_id)
    query = select(Job).where(
        Job.user_id == user.id, Job.video_id == video_id, Job.kind == "PROCESS"
    )
    if job_id:
        query = query.where(Job.id == job_id)
    job = db.scalar(query.order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    if not job:
        raise ApiError(404, "not_found", "Processing job not found.")
    rows = db.scalars(
        select(ClipSuggestion)
        .where(
            ClipSuggestion.job_id == job.id,
            ClipSuggestion.user_id == user.id,
            ClipSuggestion.video_id == video_id,
        )
        .order_by(ClipSuggestion.rank)
        .limit(limit)
    )
    result = SuggestionsView(
        job_id=job.id,
        state=job.state,
        stage=job.stage,
        error_code=job.error_code,
        items=[
            SuggestionView(
                id=r.id, rank=r.rank, job_id=r.job_id, transcript_id=r.transcript_id, **r.data
            )
            for r in rows
        ],
    )
    db.commit()
    return result
