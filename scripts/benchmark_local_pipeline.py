"""Opt-in Linux offline diagnostic; no DB/RQ/customer writes or paid providers.

Run in an isolated network-none container with the source mounted read-only.
The selection fixture proves only local schema/selection integration, not Gemini
quality, remote latency, token usage or a successful real-provider pipeline.
"""

import argparse
import hashlib
import json
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from zoclip.ai import audio, selection
from zoclip.ai.providers import LocalWhisperProviders, gemini_body
from zoclip.ai.schemas import Moment
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.media.probe import probe
from zoclip.media.storage import LocalStorage
from zoclip.rendering.engine import render
from zoclip.rendering.schemas import Preferences


def block_network(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
        raise RuntimeError("Offline benchmark forbids networking")


def benchmark(source: Path, work: Path) -> dict:
    """work must be a new disposable directory, never the deployed media root."""
    work.mkdir(mode=0o700, exist_ok=False)
    settings = Settings(
        _env_file=None,
        _secrets_dir=None,
        database_url="postgresql+psycopg://unused/unused",
        media_root=str(work),
        gemini_model="gemini-3.1-flash-lite",
    )
    if (
        settings.ai_enabled
        or settings.private_staging
        or settings.enable_live_payments
        or settings.payment_provider != "disabled"
        or settings.deepgram_api_key.get_secret_value()
        or settings.gemini_api_key.get_secret_value()
        or settings.transcription_provider != "whisper"
    ):
        raise RuntimeError("Benchmark requires an isolated environment with no credentials")
    metadata = probe(source, settings.ffprobe_binary)
    if metadata["duration_seconds"] > 7200 or source.stat().st_size > settings.media_max_bytes:
        raise RuntimeError("Source exceeds unchanged media limits")
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    storage = LocalStorage(str(work))
    phases = []

    def measure(name, operation):
        before = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        value = operation()
        after = resource.getrusage(resource.RUSAGE_SELF)
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        phases.append(
            {
                "phase": name,
                "wall_seconds": time.monotonic() - started,
                "cpu_seconds": after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime
                + child_after.ru_utime
                + child_after.ru_stime
                - children.ru_utime
                - children.ru_stime,
                "process_peak_rss_kib_cumulative": after.ru_maxrss,
                "child_peak_rss_kib_cumulative": child_after.ru_maxrss,
                "materialized_work_bytes": sum(
                    p.stat().st_size for p in work.iterdir() if p.is_file()
                ),
            }
        )
        return value

    source_id, audio_id = uuid4(), uuid4()
    measure(
        "copy_to_disposable_storage_not_http_upload",
        lambda: shutil.copyfile(source, storage.path(source_id)),
    )
    _, seconds = measure(
        "ffmpeg_audio_extraction",
        lambda: audio.extract(
            storage,
            source_id,
            audio_id,
            settings.ffmpeg_binary,
            metadata["duration_seconds"],
            lambda: None,
        ),
    )
    response = measure(
        "cold_local_whisper",
        lambda: LocalWhisperProviders(settings).transcribe(storage.path(audio_id)),
    )
    transcript = selection.transcript(response["body"], seconds)
    if not transcript.words:
        raise RuntimeError("Available source produced no timed words")
    bodies = [
        gemini_body(selection.prompt(c, settings, 3), settings)
        for c in selection.chunks(transcript.words, settings)
    ]
    serialized = sum(len(json.dumps(b, ensure_ascii=False).encode()) + 1024 for b in bodies)
    start = transcript.words[0].start
    end = min(transcript.words[-1].end, start + 30)
    candidate = Moment(
        start_sec=start,
        end_sec=end,
        title="Local fixture",
        hook="Mock selection",
        reason="Deterministic fixture, not provider-selected content",
        score=50,
        keywords=[],
        hashtags=[],
    )
    moments = measure(
        "mock_gemini_selection",
        lambda: selection.select_moments(
            [candidate],
            transcript.words,
            metadata["duration_seconds"],
            settings,
            3,
        ),
    )
    if not moments:
        raise RuntimeError("No valid mock interval; do not invent a deliverable")
    moment = moments[0]
    prefs = Preferences(
        start_ms=round(moment.start_sec * 1000), end_ms=round(moment.end_sec * 1000)
    )
    words = [w.model_dump() for w in transcript.words]
    outputs = []
    for name in ("initial_captioned_tracked_render", "prepaid_edit_rerender"):
        target = work / (name + ".mp4")
        result = measure(
            name,
            lambda target=target: render(
                storage.path(source_id),
                target,
                prefs,
                words,
                settings,
                lambda: None,
            ),
        )
        measure(name + "_local_download_read_not_http", lambda target=target: target.read_bytes())
        outputs.append({"bytes": result["size_bytes"], "sha256": result["sha256"]})
    calls = 0

    def canceled():
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ApiError(409, "job_canceled", "Benchmark cancellation fixture")

    try:
        render(storage.path(source_id), work / "canceled.mp4", prefs, words, settings, canceled)
        raise RuntimeError("Cancellation did not stop the renderer")
    except ApiError as exc:
        if exc.code != "job_canceled":
            raise
    with source.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
            raise RuntimeError("Read-only source changed")
    return {
        "source_duration_seconds": seconds,
        "source_bytes": source.stat().st_size,
        "source_sha256": digest,
        "phases": phases,
        "initial_outputs": len(moments),
        "requested_outputs": 3,
        "edited_outputs": 1,
        "outputs": outputs,
        "transcript_word_count": len(transcript.words),
        "gemini_mode": "deterministic mock selection; no provider invocation",
        "gemini_requests_if_uncached": len(bodies),
        "gemini_input_admission_units": serialized,
        "gemini_output_admission_units": len(bodies) * settings.ai_max_output_tokens,
        "actual_tokens_and_remote_latency": None,
        "queue_wait_seconds": None,
        "http_upload_download_measured": False,
        "retry_failure_rates_measured": False,
        "cancellation_stopped_renderer": True,
        "paid_calls": 0,
        "customer_records_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--allow-local-benchmark", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_benchmark:
        parser.error("Explicit local CPU/disk benchmark opt-in required")
    sys.addaudithook(block_network)
    with tempfile.TemporaryDirectory(prefix="zoclip-capacity-") as temporary:
        print(json.dumps(benchmark(args.source.resolve(), Path(temporary) / "objects")))


if __name__ == "__main__":
    main()
