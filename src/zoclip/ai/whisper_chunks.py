"""One bounded local window per queue claim; durable receipts precede progress.

No paid requests, schema or credit policy changes. The final bounded word list is
required by TranscriptData; PCM and intermediate chunk responses are never pooled.
"""

import math
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker

from zoclip.ai import audio, selection
from zoclip.ai.models import AIRequest, Transcript
from zoclip.ai.providers import LocalWhisperProviders
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.media import service
from zoclip.media.storage import LocalStorage


def window(
    index: int, duration: float, seconds: int, overlap: float
) -> tuple[float, float, float, float]:
    core_start, core_end = index * seconds, min(duration, (index + 1) * seconds)
    if not 0 <= core_start < core_end <= duration:
        raise ValueError("Invalid local window")
    return max(0, core_start - overlap), min(duration, core_end + overlap), core_start, core_end


def append_window(
    words: list[dict],
    raw: dict,
    start: float,
    stop: float,
    core_start: float,
    core_end: float,
    duration: float,
) -> None:
    data = selection.transcript(raw, stop - start)
    for local in data.words:
        word = local.model_dump()
        word["start"] = round(word["start"] + start, 6)
        word["end"] = round(word["end"] + start, 6)
        middle = (word["start"] + word["end"]) / 2
        # Half-open ownership prevents duplicate tokens in shared context. Do not
        # remove repeated words merely because their spelling happens to match.
        if middle < core_start or (middle >= core_end and core_end < duration):
            continue
        if words and word["start"] < words[-1]["end"] - 0.05:
            previous = words[-1]

            def normalize(s: str) -> str:
                return "".join(c for c in s.casefold() if c.isalnum())

            if normalize(word["word"]) and normalize(word["word"]) == normalize(previous["word"]):
                # Retain the first timing, but keep punctuation recovered by the
                # second window's extra right context (e.g. "word" -> "word!").
                if (
                    word["punctuated_word"][-1:].isalnum() is False
                    and previous["punctuated_word"][-1:].isalnum()
                ):
                    previous["word"] = word["word"]
                    previous["punctuated_word"] = word["punctuated_word"]
                continue
            raise ApiError(422, "whisper_boundary_conflict", "Chunk boundary alignment conflicted.")
        if word["end"] > duration or len(words) >= 40000:
            raise ApiError(422, "invalid_transcription", "Local transcription exceeded limits.")
        words.append(word)


def run_chunk(
    factory: sessionmaker,
    settings: Settings,
    storage: LocalStorage,
    providers: LocalWhisperProviders,
    owner: UUID,
    job_id: UUID,
    token: UUID,
    transcript_key: str,
    source_id: UUID,
    source_digest: str,
    duration: int,
    media_duration: float,
) -> None:
    from zoclip.ai.worker import checked, local_request, requeue, stage

    claim_start = time.monotonic()
    last_heartbeat = 0.0

    def heartbeat() -> None:
        nonlocal last_heartbeat
        if time.monotonic() - last_heartbeat < 3:
            return
        with factory() as db:
            job = checked(db, owner, job_id, token)
            service.mutex(db, owner)
            service.capacity(db, settings, storage)
            job.heartbeat_at = utcnow()
            db.commit()
        last_heartbeat = time.monotonic()

    with factory() as db:
        job = checked(db, owner, job_id, token)
        saved = job.checkpoint.get("whisper_audio")
        if saved is None:
            saved = {"id": str(uuid4()), "ready": False, "source": source_digest}
            job.checkpoint = {**job.checkpoint, "whisper_chunks_v2": True, "whisper_audio": saved}
            db.commit()
        if saved["source"] != source_digest:
            raise ApiError(409, "invalid_transcription", "Source identity changed.")
        audio_id = UUID(saved["id"])
        index = job.checkpoint.get("whisper_chunk_index", 0)
    if not saved["ready"]:
        storage.delete(audio_id)
        digest, seconds = audio.extract(
            storage, source_id, audio_id, settings.ffmpeg_binary, duration, heartbeat
        )
        saved = {**saved, "ready": True, "sha256": digest, "duration": seconds}
        with factory() as db:
            job = checked(db, owner, job_id, token)
            job.checkpoint = {**job.checkpoint, "whisper_audio": saved}
            db.commit()
    seconds = min(saved["duration"], media_duration)
    total = math.ceil(seconds / settings.whisper_chunk_seconds)
    # Transcribe windows in bounded parallel batches inside one claim instead
    # of requeueing after every window. Receipts stay journaled per window via
    # local_request (replays are free), the checkpoint still appends request
    # ids strictly in window order after each batch, and the claim stops on
    # its time budget so the RQ timeout and job lease are never outlived.
    # A batch may only START while the claim retains a full per-window
    # deadline (300s in the provider) of headroom under the RQ hard timeout:
    # the between-batch budget check alone cannot stop a slow batch from
    # straddling the wall (observed: JobTimeoutException at 660s with
    # 1-thread windows, 2026-10-20 benchmark).
    initial_index = index
    while index < total:
        if index > initial_index and (
            time.monotonic() - claim_start
            > min(
                settings.whisper_claim_budget_seconds,
                settings.whisper_batch_headroom_seconds,
            )
        ):
            with factory() as db:
                job = checked(db, owner, job_id, token)
                requeue(db, job)
                db.commit()
            return
        batch = list(
            range(index, min(total, index + max(1, settings.whisper_parallelism)))
        )
        exhausted = index + len(batch) >= total
        with factory() as db:
            job = checked(db, owner, job_id, token)
            stage(db, job, "TRANSCRIBING")
            db.commit()

        def transcribe_window(i: int) -> str:
            start, stop, core_start, core_end = window(
                i, seconds, settings.whisper_chunk_seconds, settings.whisper_overlap_seconds
            )
            key = money.fingerprint([transcript_key, job_id, "window", i, start, stop])
            response = local_request(
                factory,
                settings,
                storage,
                providers,
                owner,
                job_id,
                token,
                key,
                audio_id,
                operation=lambda: providers.transcribe_chunk(
                    storage.path(audio_id),
                    start,
                    stop,
                    heartbeat,
                    owned_start=core_start - start,
                    owned_end=core_end - start,
                ),
            )
            # Validate every chunk before durable progress. No partial transcript is exposed.
            selection.transcript(response["body"], stop - start)
            return str(response["local_request_id"])

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            batch_ids = list(pool.map(transcribe_window, batch))
        over_budget = (
            time.monotonic() - claim_start > settings.whisper_claim_budget_seconds
        )
        with factory() as db:
            job = checked(db, owner, job_id, token)
            ids = job.checkpoint.get("whisper_chunk_requests", [])
            if len(ids) != index:
                raise ApiError(409, "invalid_transcription", "Local checkpoint index conflicted.")
            job.checkpoint = {
                **job.checkpoint,
                "whisper_chunk_index": index + len(batch),
                "whisper_chunk_requests": [*ids, *batch_ids],
            }
            if not exhausted and over_budget:
                requeue(db, job)
            db.commit()
        index += len(batch)
        if not exhausted and over_budget:
            return

    words: list[dict] = []
    with factory() as db:
        job = checked(db, owner, job_id, token)
        ids = job.checkpoint["whisper_chunk_requests"]
        if len(ids) != total:
            raise ApiError(409, "invalid_transcription", "Local checkpoints incomplete.")
        db.commit()
    # Fetch a single response at a time; retain only the contract's bounded words.
    for i, request_id in enumerate(ids):
        heartbeat()
        with factory() as db:
            row = service.owned(db, AIRequest, owner, UUID(request_id))
            if row.job_id != job_id or row.provider != "whisper" or row.state != "RECORDED":
                raise ApiError(409, "invalid_transcription", "Local receipt unavailable.")
            raw = row.response["body"]
            start, stop, core_start, core_end = window(
                i, seconds, settings.whisper_chunk_seconds, settings.whisper_overlap_seconds
            )
            append_window(words, raw, start, stop, core_start, core_end, seconds)
    result: dict = {
        "status": 200,
        "body": {
            "metadata": {"duration": seconds},
            "results": {"channels": [{"alternatives": [{"words": words}]}], "utterances": []},
        },
    }
    data = selection.transcript(result["body"], seconds)
    with factory() as db:
        job = checked(db, owner, job_id, token)
        cached = Transcript(
            user_id=owner,
            video_id=job.video_id,
            job_id=job.id,
            request_id=UUID(ids[-1]),
            cache_key=transcript_key,
            model="faster-whisper:" + settings.whisper_model,
            language=settings.deepgram_language,
            audio_sha256=saved["sha256"],
            data=data.model_dump(mode="json"),
        )
        db.add(cached)
        db.flush()
        job.checkpoint = {**job.checkpoint, "transcript_id": str(cached.id)}
        if not data.words:
            service.terminate(db, job, "FAILED", "no_speech")
        else:
            requeue(db, job)
        db.commit()
    storage.delete(audio_id)
