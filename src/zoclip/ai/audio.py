import hashlib
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from uuid import UUID

from zoclip.core.errors import ApiError
from zoclip.media.storage import LocalStorage


def extract(
    storage: LocalStorage,
    source: UUID,
    target: UUID,
    binary: str,
    duration: int,
    heartbeat: Callable[[], None],
) -> tuple[str, float]:
    """16 kHz mono PCM, preserves source timeline including leading audio offset."""
    with storage.create(target):
        pass
    prefix = [] if sys.platform == "win32" else [sys.executable, "-m", "zoclip.ai.audio_runner"]
    args = prefix + [
        binary,
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "mov,matroska,webm",
        "-threads",
        "2",
        # Auto-sized filter pools can fail pthread creation under the bounded
        # extractor address space on long inputs. Keep one audio filter thread.
        "-filter_threads",
        "1",
        "-copyts",
        "-start_at_zero",
        "-i",
        str(storage.path(source)),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        "aresample=16000:async=1:first_pts=0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-threads",
        "2",
        "-t",
        str(duration),
        "-f",
        "wav",
        "-y",
        str(storage.path(target)),
    ]
    # stderr is discarded: filenames/decoder text must not reach logs or grow memory.
    with subprocess.Popen(
        args, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) as p:
        deadline = time.monotonic() + 300
        try:
            while p.poll() is None:
                heartbeat()
                if (
                    time.monotonic() > deadline
                    or storage.path(target).stat().st_size > 240 * 1024**2
                ):
                    raise ApiError(
                        422, "audio_extraction_limit", "Audio extraction exceeded limits."
                    )
                time.sleep(0.1)
            if p.returncode:
                raise ApiError(422, "audio_extraction_failed", "Audio extraction failed.")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
    with storage.open(target) as handle:
        with wave.open(handle, "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
            if (
                audio.getnchannels() != 1
                or audio.getframerate() != 16000
                or not 0 < seconds <= duration
            ):
                raise ApiError(422, "invalid_audio", "Extracted audio failed validation.")
        handle.seek(0)
        digest_state = hashlib.sha256()
        while chunk := handle.read(65536):
            digest_state.update(chunk)
        digest = digest_state.hexdigest()
    return digest, seconds
