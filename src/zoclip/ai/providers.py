"""Official HTTPS REST adapters, no implicit retries or configurable destinations."""

import json
import math
import os
import ssl
import sys
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx

from zoclip.ai.schemas import Moments
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError

MAX_RESPONSE = 8 * 1024**2


class ProviderFailure(Exception):
    """Unknown remote outcome: NEVER permission to retry a paid request."""


class Providers(Protocol):
    def transcribe(self, path: Path) -> dict: ...
    def analyze(self, body: dict) -> dict: ...


def gemini_body(prompt: str, settings: Settings) -> dict:
    generation = {
        "candidateCount": 1,
        "maxOutputTokens": settings.ai_max_output_tokens,
        "responseMimeType": "application/json",
        "responseJsonSchema": Moments.model_json_schema(),
    }
    if settings.gemini_model == "gemini-3.1-flash-lite":
        generation["thinkingConfig"] = {"thinkingLevel": "minimal"}
        # Gemini 3 recommends its default temperature (1.0). Minimal is NOT
        # thinking-off: usage accounting still includes all residual tokens.
    else:
        generation.update(temperature=0.2, thinkingConfig={"thinkingBudget": 0})
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation,
    }


class HTTPProviders:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings, self.transport = settings, transport

    def request(
        self, url: str, headers: dict, *, limit: int = MAX_RESPONSE, **kwargs: object
    ) -> dict:
        deadline = time.monotonic() + self.settings.ai_provider_timeout_seconds
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.settings.ai_provider_timeout_seconds, connect=10),
                trust_env=False,
                verify=ssl.create_default_context(),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                with client.stream("POST", url, headers=headers, **kwargs) as response:  # type: ignore[arg-type]
                    data = bytearray()
                    for chunk in response.iter_bytes(65536):
                        if time.monotonic() > deadline or len(data) + len(chunk) > limit:
                            raise ProviderFailure("provider_response_limit")
                        data.extend(chunk)
                    try:
                        body = json.loads(data)
                    except (ValueError, UnicodeError):
                        body = None
                    return {"status": response.status_code, "body": body}
        except httpx.HTTPError as exc:
            raise ProviderFailure("provider_outcome_unknown") from exc

    def transcribe(self, path: Path) -> dict:
        s = self.settings
        with path.open("rb") as audio:
            return self.request(
                "https://api.deepgram.com/v1/listen",
                {
                    "Authorization": "Token " + s.deepgram_api_key.get_secret_value(),
                    "Content-Type": "audio/wav",
                },
                params={
                    "model": s.deepgram_model,
                    "version": s.deepgram_version,
                    "language": s.deepgram_language,
                    "punctuate": "true",
                    "diarize": str(s.deepgram_diarize).lower(),
                    "utterances": str(s.deepgram_utterances).lower(),
                    "mip_opt_out": str(s.deepgram_mip_opt_out).lower(),
                },
                content=iter(lambda: audio.read(65536), b""),
            )

    def analyze(self, body: dict) -> dict:
        return self.request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + self.settings.gemini_model
            + ":generateContent",
            {"x-goog-api-key": self.settings.gemini_api_key.get_secret_value()},
            limit=256 * 1024,
            json=body,
        )


_whisper_lock = threading.Lock()
_whisper_models: dict[tuple, object] = {}
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def check_whisper_files(settings: Settings) -> Path:
    """Local paths only. Missing assets never authorize a runtime download."""
    path = Path(settings.whisper_model_path)
    if not path.is_absolute() or not path.is_dir():
        raise ProviderFailure("whisper_model_unavailable")
    if any(not (path / name).is_file() for name in WHISPER_FILES):
        raise ProviderFailure("whisper_model_unavailable")
    return path


def _load_whisper(settings: Settings) -> object:
    import onnxruntime
    from faster_whisper import WhisperModel

    onnxruntime.disable_telemetry_events()
    return WhisperModel(
        str(check_whisper_files(settings)),
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )


class LocalWhisperProviders(HTTPProviders):
    """Local audio, shared unchanged Gemini adapter; never automatic paid fallback.

    Lazy process-local reuse is safe for RQ's forked work horses. The shared media
    lock also serializes separate processes/containers, released by the OS on crash.
    Speaker 0 is a placeholder, not diarization.
    """

    def transcribe(self, path: Path) -> dict:
        return self.transcribe_chunk(path, 0, None)

    def transcribe_chunk(
        self,
        path: Path,
        start: float,
        end: float | None,
        progress: Callable[[], None] = lambda: None,
        *,
        owned_start: float = 0,
        owned_end: float | None = None,
    ) -> dict:
        # Never give the decoder/VAD a whole long recording. Read only this bounded
        # PCM window; the worker checkpoints each window in a separate RQ claim.
        import numpy as np

        deadline = time.monotonic() + 300
        progress()
        try:
            # The existing extractor supplies bounded mono 16kHz PCM WAV. Validate
            # actual samples rather than VAD's shorter duration_after_vad value.
            with wave.open(str(path), "rb") as source:
                duration = source.getnframes() / source.getframerate()
                if (
                    source.getnchannels() != 1
                    or source.getframerate() != 16000
                    or source.getsampwidth() != 2
                    or not 0 < duration <= 7200
                    or path.stat().st_size > 240 * 1024**2
                ):
                    raise ValueError
                stop = duration if end is None else end
                if (
                    not 0 <= start < stop <= duration
                    or stop - start
                    > self.settings.whisper_chunk_seconds
                    + 2 * self.settings.whisper_overlap_seconds
                ):
                    raise ValueError
                first, last = round(start * 16000), round(stop * 16000)
                source.setpos(first)
                data = source.readframes(last - first)
                if len(data) != (last - first) * 2:
                    raise ValueError
                samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
                samples /= 32768.0
                del data
                duration = (last - first) / 16000
                owned_stop = duration if owned_end is None else owned_end
                if not 0 <= owned_start < owned_stop <= duration + 1 / 16000:
                    raise ValueError
        except Exception:
            raise ProviderFailure("whisper_invalid_audio") from None

        try:
            with _whisper_lock:
                # One host-wide transcription on the existing shared private volume.
                # Nonblocking acquisition fails closed rather than holding job leases.
                lock_path = Path(self.settings.media_root) / ".whisper-transcription.lock"
                with lock_path.open("a+b") as lock:
                    if sys.platform != "win32":
                        import fcntl

                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    else:
                        import msvcrt

                        lock.seek(0)
                        if not lock.read(1):
                            lock.write(b"0")
                            lock.flush()
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    key = (
                        os.getpid(),
                        self.settings.whisper_model_path,
                        self.settings.whisper_model,
                        self.settings.whisper_device,
                        self.settings.whisper_compute_type,
                    )
                    if key not in _whisper_models:
                        _whisper_models[key] = _load_whisper(self.settings)
                    model = _whisper_models[key]
                    segments, _info = model.transcribe(  # type: ignore[attr-defined]
                        samples,
                        language=self.settings.deepgram_language,
                        vad_filter=True,
                        word_timestamps=True,
                    )
                    words: list[dict] = []
                    pending: list = []
                    # Iteration performs inference; exceptions must not yield success.
                    for segment in segments:
                        progress()
                        if time.monotonic() > deadline:
                            raise ProviderFailure("whisper_deadline_exceeded")
                        if segment.words is None:
                            raise ValueError
                        for w in segment.words:
                            text = w.word.strip()
                            if (
                                not text
                                or len(text) > 200
                                or len(words) >= 40000
                                or any(
                                    isinstance(v, bool)
                                    or not isinstance(v, (int, float))
                                    or not math.isfinite(v)
                                    for v in (w.start, w.end, w.probability)
                                )
                                or not 0 <= w.start <= w.end <= duration
                                or not 0 <= w.probability <= 1
                                or (words and w.start < words[-1]["end"] - 0.05)
                            ):
                                raise ValueError
                            if w.start == w.end:
                                # Native alignment can emit a real zero-length token.
                                # Preserve its text at an already-timed boundary; never
                                # invent a positive duration or silently drop the token.
                                if (
                                    not words
                                    or not words[-1]["start"] <= w.start <= words[-1]["end"]
                                ):
                                    # Only unanchored context is deferred to its
                                    # neighboring chunk. Anchored punctuation still
                                    # belongs to its timed word, even at the seam.
                                    if w.start < owned_start or (
                                        owned_stop < duration and w.start >= owned_stop
                                    ):
                                        continue
                                    if len(pending) >= 20:
                                        raise ValueError
                                    pending.append(w)
                                    continue
                                previous = words[-1]
                                separator = " " if w.word[:1].isspace() else ""
                                combined = previous["punctuated_word"] + separator + text
                                if len(combined) > 200:
                                    raise ValueError
                                previous.update(
                                    word=combined,
                                    punctuated_word=combined,
                                    confidence=min(previous["confidence"], w.probability),
                                )
                                continue
                            confidence = w.probability
                            if pending:
                                if any(not w.start <= token.start <= w.end for token in pending):
                                    raise ValueError
                                text = ("".join(token.word for token in pending) + w.word).strip()
                                confidence = min(
                                    confidence, *(token.probability for token in pending)
                                )
                                pending.clear()
                                if len(text) > 200:
                                    raise ValueError
                            words.append(
                                {
                                    "word": text,
                                    "punctuated_word": text,
                                    "start": w.start,
                                    "end": w.end,
                                    "confidence": confidence,
                                    "speaker": 0,
                                }
                            )
                    progress()
                    if time.monotonic() > deadline:
                        raise ProviderFailure("whisper_deadline_exceeded")
                    if pending:
                        raise ValueError
                    return {
                        "status": 200,
                        "body": {
                            "metadata": {"duration": duration},
                            "results": {
                                "channels": [{"alternatives": [{"words": words}]}],
                                "utterances": [],
                            },
                        },
                    }
        except (ProviderFailure, ApiError):
            raise
        except Exception:
            # No decoder/native-model error or chained sensitive path reaches logs.
            raise ProviderFailure("whisper_transcription_failed") from None
