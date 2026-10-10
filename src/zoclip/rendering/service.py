"""Owner-serialized revisions, explicit selection, export quotas and admission."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zoclip.ai.models import ClipSuggestion
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction, Quote
from zoclip.media import service as media
from zoclip.media.models import Job, Outbox, SourceVideo, StorageObject
from zoclip.media.storage import LocalStorage
from zoclip.rendering.models import Clip, ClipRevision, RenderOutput
from zoclip.rendering.schemas import Preferences, RenderInput


def retained(db: Session, owner: UUID, video_id: UUID) -> SourceVideo:
    video = media.owned(db, SourceVideo, owner, video_id, lock=True)
    if video.state != "READY" or video.expires_at <= utcnow():
        raise ApiError(409, "source_not_ready", "A retained source is required.")
    return video


def revision(db: Session, clip: Clip, number: int | None = None) -> ClipRevision:
    return db.scalars(
        select(ClipRevision).where(
            ClipRevision.clip_id == clip.id, ClipRevision.number == (number or clip.revision)
        )
    ).one()


def validate(db: Session, clip: Clip, prefs: Preferences) -> None:
    video = retained(db, clip.user_id, clip.video_id)
    parent = media.required(db, Job, clip.job_id)
    assert parent.reservation_id is not None
    reservation = media.required(db, CreditReservation, parent.reservation_id)
    quote = media.required(db, Quote, reservation.quote_id)
    if prefs.end_ms > video.metadata_json["duration_ms"]:
        raise ApiError(422, "invalid_trim", "Trim exceeds validated source duration.")
    if prefs.captions and not quote.request["captions"]:
        raise ApiError(409, "feature_not_reserved", "Captions were not included in the quote.")
    if prefs.frame != "pad" and not quote.request["reframe"]:
        raise ApiError(409, "feature_not_reserved", "Crop was not included in the quote.")
    if prefs.words is not None:
        previous = prefs.start_ms
        for word in prefs.words:
            if word.start_ms < previous or word.end_ms > prefs.end_ms:
                raise ApiError(
                    422, "invalid_captions", "Edited words must be ordered within the trim."
                )
            previous = word.end_ms


def create(db: Session, owner: UUID, suggestion_id: UUID) -> Clip:
    media.mutex(db, owner)
    suggestion = media.owned(db, ClipSuggestion, owner, suggestion_id)
    retained(db, owner, suggestion.video_id)
    parent = media.owned(db, Job, owner, suggestion.job_id, lock=True)
    old = db.scalar(select(Clip).where(Clip.suggestion_id == suggestion.id))
    if old:
        return old
    if parent.state != "SUGGESTIONS_READY" or parent.checkpoint.get("render_selection"):
        raise ApiError(409, "selection_closed", "Selection is closed for this job.")
    assert parent.reservation_id is not None
    reservation = media.required(db, CreditReservation, parent.reservation_id)
    quote = media.required(db, Quote, reservation.quote_id)
    if (
        db.scalar(select(func.count()).select_from(Clip).where(Clip.job_id == parent.id)) or 0
    ) >= quote.request["output_count"]:
        raise ApiError(409, "export_limit", "Reserved output count reached.")
    clip = Clip(
        user_id=owner, video_id=suggestion.video_id, job_id=parent.id, suggestion_id=suggestion.id
    )
    db.add(clip)
    db.flush()
    data = suggestion.data
    prefs = Preferences(
        start_ms=round(data["start_sec"] * 1000),
        end_ms=round(data["end_sec"] * 1000),
        title=data["title"],
        hashtags=data["hashtags"],
        captions=quote.request["captions"],
        frame="track" if quote.request["reframe"] else "pad",
    )
    validate(db, clip, prefs)
    db.add(ClipRevision(clip_id=clip.id, number=1, preferences=prefs.model_dump()))
    db.flush()
    return clip


def edit(db: Session, owner: UUID, clip_id: UUID, number: int, prefs: Preferences) -> Clip:
    media.mutex(db, owner)
    clip = media.owned(db, Clip, owner, clip_id, lock=True)
    if number != clip.revision:
        raise ApiError(409, "revision_conflict", "Reload the current clip revision.")
    parent = media.required(db, Job, clip.job_id)
    if parent.state not in {"SUGGESTIONS_READY", "COMPLETED"}:
        raise ApiError(409, "render_busy", "Wait for the active render before editing.")
    if db.scalar(
        select(RenderOutput.id)
        .join(Job, Job.id == RenderOutput.job_id)
        .where(RenderOutput.clip_id == clip.id, Job.state.in_(media.ACTIVE))
        .limit(1)
    ):
        raise ApiError(409, "render_busy", "A render is active for this clip.")
    # Metadata-only revisions do not consume an export. Bound history separately.
    if clip.revision >= 101:
        raise ApiError(409, "revision_limit", "Revision history limit reached.")
    validate(db, clip, prefs)
    clip.revision += 1
    db.add(ClipRevision(clip_id=clip.id, number=clip.revision, preferences=prefs.model_dump()))
    db.flush()
    return clip


def budget(
    db: Session, settings: Settings, owner: UUID | None = None, reservation_id: UUID | None = None
) -> tuple[UUID, UUID, int]:
    _, _, limits = money.locked_limits(db)
    rates = money.configured_rates(db, limits)
    # Shared two-thread wall bound plus bounded probes. Missing/undersized estimates fail closed.
    units = settings.render_deadline_seconds * 2 + 40
    denominator = 1024**3 * 86400
    storage_units = (
        settings.render_max_bytes * settings.media_retention_seconds + denominator - 1
    ) // denominator
    if units > limits.render_cpu_seconds_per_output or units > rates["render"].max_units:
        raise ApiError(
            503, "render_estimate_unconfigured", "Configure a sufficient render CPU estimate."
        )
    if (
        storage_units > limits.storage_gb_days_per_output
        or storage_units > rates["storage"].max_units
    ):
        raise ApiError(
            503, "render_estimate_unconfigured", "Configure a sufficient retention estimate."
        )
    if owner is not None:
        money.check_budgets(
            db,
            limits,
            owner,
            reservation_id,
            rates["render"].unit_usd * units + rates["storage"].unit_usd * storage_units,
        )
    return rates["render"].id, rates["storage"].id, units


def output(db: Session, clip: Clip, job: Job, settings: Settings, storage: LocalStorage) -> None:
    prefs = Preferences.model_validate(revision(db, clip).preferences)
    validate(db, clip, prefs)
    # Includes encoded MP4, duplicate promotion scratch and subtitle/tracking metadata.
    maximum = settings.render_max_bytes
    media.capacity(db, settings, storage, 2 * maximum)
    obj = StorageObject(user_id=clip.user_id, reserved_bytes=2 * maximum)
    db.add(obj)
    db.flush()
    db.add(
        RenderOutput(
            user_id=clip.user_id,
            clip_id=clip.id,
            revision=clip.revision,
            job_id=job.id,
            object_id=obj.id,
        )
    )


def select_clips(
    db: Session,
    owner: UUID,
    job_id: UUID,
    ids: list[UUID],
    key: str,
    settings: Settings,
    storage: LocalStorage,
) -> Job:
    media.mutex(db, owner)
    job = media.owned(db, Job, owner, job_id, lock=True)
    hashed = money.fingerprint([str(i) for i in ids])
    if job.checkpoint.get("render_selection"):
        money.same(job.checkpoint["render_selection_hash"], hashed)
        if job.checkpoint["render_key"] != key:
            raise ApiError(409, "selection_closed", "This job already has an approved selection.")
        return job
    if job.state != "SUGGESTIONS_READY" or len(set(ids)) != len(ids):
        raise ApiError(409, "invalid_selection", "Select unique clips from an available job.")
    reservation = media.required(db, CreditReservation, job.reservation_id)
    quote = media.required(db, Quote, reservation.quote_id)
    if len(ids) > quote.request["output_count"]:
        raise ApiError(409, "export_limit", "Selection exceeds the accepted quote.")
    media.pending_gate(db, settings)
    budget(db, settings, owner, reservation.id)
    for clip_id in ids:
        clip = media.owned(db, Clip, owner, clip_id, lock=True)
        if clip.job_id != job.id:
            raise ApiError(409, "invalid_selection", "All clips must belong to this job.")
        output(db, clip, job, settings, storage)
        db.flush()
    job.checkpoint = {
        **job.checkpoint,
        "render_selection": True,
        "render_selection_hash": hashed,
        "render_key": key,
    }
    media.event(db, job, "QUEUED")
    job.generation += 1
    db.add(Outbox(job_id=job.id, generation=job.generation))
    return job


def rerender(
    db: Session,
    owner: UUID,
    clip_id: UUID,
    data: RenderInput,
    key: str,
    settings: Settings,
    storage: LocalStorage,
) -> Job:
    media.mutex(db, owner)
    hashed = money.fingerprint([str(clip_id), data.model_dump(mode="json")])
    old = db.scalar(select(Job).where(Job.user_id == owner, Job.operation_key == key))
    if old:
        money.same(old.request_hash, hashed)
        return old
    clip = media.owned(db, Clip, owner, clip_id, lock=True)
    parent = media.required(db, Job, clip.job_id)
    if parent.state != "COMPLETED" or data.revision != clip.revision:
        raise ApiError(
            409, "revision_conflict", "A completed parent and current revision are required."
        )
    if db.scalar(
        select(RenderOutput.id).where(
            RenderOutput.clip_id == clip.id, RenderOutput.revision == clip.revision
        )
    ):
        raise ApiError(409, "already_rendered", "This revision already has an export request.")
    assert parent.reservation_id is not None
    original = media.required(db, CreditReservation, parent.reservation_id)
    original_quote = media.required(db, Quote, original.quote_id)
    if not db.scalar(
        select(RenderOutput.id).where(
            RenderOutput.clip_id == clip.id,
            RenderOutput.job_id == parent.id,
            RenderOutput.state == "COMPLETE",
        )
    ):
        raise ApiError(409, "not_selected", "This clip was not in the completed selection.")
    # Successful/active edits consume a shared quota. Failed edits retain sunk expense,
    # but do not consume the customer's prepaid deliverable allowance.
    used = (
        db.scalar(
            select(func.count())
            .select_from(RenderOutput)
            .join(Clip)
            .where(
                Clip.job_id == parent.id,
                RenderOutput.job_id != parent.id,
                RenderOutput.state.in_({"PENDING", "COMPLETE"}),
            )
        )
        or 0
    )
    settlement = db.scalar(
        select(CreditTransaction.id).where(
            CreditTransaction.reservation_id == original.id, CreditTransaction.operation == "SETTLE"
        )
    )
    refunded = db.scalar(
        select(CreditTransaction.id).where(
            CreditTransaction.original_id == settlement, CreditTransaction.operation == "REFUND"
        )
    )
    included = used < original_quote.request["edit_count"] and not refunded
    if used >= money.active_price(db, owner).rules["max_edits"]:
        raise ApiError(409, "edit_limit", "Plan export/edit limit reached.")
    media.pending_gate(db, settings)
    budget(db, settings, owner, original.id if included else None)
    job = Job(
        id=uuid4(),
        user_id=owner,
        video_id=clip.video_id,
        kind="RENDER",
        operation_key=key,
        request_hash=hashed,
        checkpoint={
            "render_selection": True,
            "included_edit": included,
            "expense_reservation": str(original.id) if included else None,
        },
    )
    db.add(job)
    if not included:
        if data.quote_id is None:
            raise ApiError(409, "quote_required", "Request and accept a new export quote.")
        quote = media.owned(db, Quote, owner, data.quote_id)
        video = retained(db, owner, clip.video_id)
        prefs = Preferences.model_validate(revision(db, clip).preferences)
        if (
            quote.request["source_seconds"] != video.metadata_json["duration_seconds"]
            or quote.request["output_count"] != 1
            or quote.request["edit_count"] != 0
            or quote.request["captions"] != prefs.captions
            or quote.request["reframe"] != (prefs.frame != "pad")
        ):
            raise ApiError(409, "quote_mismatch", "Use a one-output quote matching this revision.")
        reservation = money.reserve(
            db,
            owner,
            quote.id,
            job.id,
            "render-reserve:" + str(job.id),
            production=settings.app_env == "production",
        )
        job.reservation_id = reservation.id
        job.checkpoint = {**job.checkpoint, "estimated_credits": reservation.credits}
    elif data.quote_id is not None:
        raise ApiError(409, "included_edit", "This export uses a prepaid edit; omit quote_id.")
    output(db, clip, job, settings, storage)
    db.flush()
    db.add(Outbox(job_id=job.id, generation=0))
    media.event(db, job, "QUEUED")
    return job
