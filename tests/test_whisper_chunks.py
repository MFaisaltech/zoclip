"""Bounded windows: global alignment, silence, duplicates and bounded PCM reads."""

import wave
from types import SimpleNamespace as Item

import pytest

from zoclip.ai import providers as p
from zoclip.ai import selection
from zoclip.ai.whisper_chunks import append_window, window
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


@pytest.fixture(autouse=True)
def _fake_batched_pipeline(monkeypatch):
    """These tests fake the model; give the batched path a delegating fake too."""

    class Pipeline:
        def __init__(self, model):
            self.model = model

        def transcribe(self, audio, **options):
            options.pop("batch_size")
            return self.model.transcribe(audio, **options)

    monkeypatch.setattr(p, "_load_batched_pipeline", Pipeline)
    monkeypatch.setattr(p, "_batched_pipelines", {})


def raw(words, duration):
    return {
        "metadata": {"duration": duration},
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "words": [
                                {
                                    "word": text,
                                    "punctuated_word": text,
                                    "start": start,
                                    "end": end,
                                    "confidence": 0.9,
                                    "speaker": 0,
                                }
                                for text, start, end in words
                            ]
                        }
                    ]
                }
            ],
            "utterances": [],
        },
    }


def test_overlapping_windows_offset_punctuation_silence_and_no_spelling_only_dedup():
    words = []
    append_window(
        words, raw([("Hello,", 0.1, 0.5), ("world", 29.6, 30.2)], 31), *window(0, 62, 30, 1), 62
    )
    # This alignment of world straddles the ownership seam but overlaps the same word.
    append_window(
        words,
        raw([("world!", 0.8, 1.3), ("yes", 2, 2.2), ("yes", 2.3, 2.5)], 32),
        *window(1, 62, 30, 1),
        62,
    )
    append_window(words, raw([], 3), *window(2, 62, 30, 1), 62)
    assert [w["punctuated_word"] for w in words] == ["Hello,", "world!", "yes", "yes"]
    assert [(w["start"], w["end"]) for w in words] == [
        (0.1, 0.5),
        (29.6, 30.2),
        (31, 31.2),
        (31.3, 31.5),
    ]
    assert selection.transcript(raw([], 62), 62).words == []


def test_incompatible_boundary_alignment_fails_without_publishing_corruption():
    words = []
    append_window(words, raw([("one", 29.6, 30.3)], 31), *window(0, 62, 30, 1), 62)
    with pytest.raises(ApiError, match="Chunk boundary"):
        append_window(words, raw([("different", 0.9, 1.3)], 32), *window(1, 62, 30, 1), 62)


def test_final_short_window_and_invalid_index():
    assert window(60, 7200.1, 120, 1) == (7199, 7200.1, 7200, 7200.1)
    with pytest.raises(ValueError):
        window(60, 7200, 120, 1)


def test_two_hour_file_only_reads_one_bounded_pcm_window(tmp_path, monkeypatch):
    audio = tmp_path / "long.wav"
    # Sparse 2-hour WAV fixture: no whole-file Python allocation.
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 7200 * 16000, "NONE", "not compressed"))
        f.writeframesraw(b"\0\0")
        f._file.seek(44 + 7200 * 16000 * 2 - 2)
        f._file.write(b"\0\0")
        f._datawritten = 7200 * 16000 * 2
        f._nframeswritten = 7200 * 16000
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused/unused", media_root=str(tmp_path)
    )
    read = []
    original = wave.Wave_read.readframes

    def bounded(self, n):
        read.append(n)
        assert n <= 122 * 16000
        return original(self, n)

    monkeypatch.setattr(wave.Wave_read, "readframes", bounded)

    def transcribe(samples, **kw):
        assert samples.dtype.name == "float32" and samples.shape == (122 * 16000,)
        assert samples.nbytes == 122 * 16000 * 4
        return iter([Item(words=[Item(word=" End!", start=1.5, end=2, probability=0.9)])]), Item()

    monkeypatch.setattr(p, "_whisper_models", {})
    monkeypatch.setattr(p, "_load_whisper", lambda _: Item(transcribe=transcribe))
    result = p.LocalWhisperProviders(settings).transcribe_chunk(audio, 119, 241)
    assert result["body"]["metadata"]["duration"] == 122
    assert read == [122 * 16000]
    with pytest.raises(p.ProviderFailure, match="invalid_audio"):
        p.LocalWhisperProviders(settings).transcribe(audio)


def test_cancellation_during_native_segment_iteration_propagates(tmp_path, monkeypatch):
    audio = tmp_path / "short.wav"
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\0\0" * 16000)
    s = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused/unused", media_root=str(tmp_path)
    )
    monkeypatch.setattr(p, "_whisper_models", {})
    monkeypatch.setattr(
        p,
        "_load_whisper",
        lambda _: Item(transcribe=lambda *a, **kw: (iter([Item(words=[])]), Item())),
    )
    calls = []

    def progress():
        calls.append(1)
        if len(calls) == 2:
            raise ApiError(409, "job_canceled", "Canceled")

    with pytest.raises(ApiError) as e:
        p.LocalWhisperProviders(s).transcribe_chunk(audio, 0, 1, progress)
    assert e.value.code == "job_canceled"


def test_existing_inference_deadline_is_not_extended_by_chunking(tmp_path, monkeypatch):
    audio = tmp_path / "deadline.wav"
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\0\0" * 16000)
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused/unused", media_root=str(tmp_path)
    )
    clock = [0.0]
    monkeypatch.setattr(p.time, "monotonic", lambda: clock[0])

    def infer(*a, **kw):
        clock[0] = 301
        return iter([Item(words=[])]), Item()

    monkeypatch.setattr(p, "_whisper_models", {})
    monkeypatch.setattr(p, "_load_whisper", lambda _: Item(transcribe=infer))
    with pytest.raises(p.ProviderFailure, match="whisper_deadline_exceeded"):
        p.LocalWhisperProviders(settings).transcribe_chunk(audio, 0, 1)


def test_unanchored_zero_tokens_only_ignored_in_neighbor_owned_context(tmp_path, monkeypatch):
    audio = tmp_path / "edge.wav"
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(122):
            f.writeframes(b"\0\0" * 16000)
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused/unused", media_root=str(tmp_path)
    )

    def infer(*a, **kw):
        return iter(
            [
                Item(
                    words=[
                        Item(word="Hello,", start=1.5, end=2, probability=0.9),
                        Item(word=" world", start=120.2, end=121, probability=0.9),
                        Item(word="!", start=121, end=121, probability=0.9),
                        *[
                            Item(word=" context", start=121.98, end=121.98, probability=0.0004)
                            for _ in range(5)
                        ],
                    ]
                )
            ]
        ), Item()

    monkeypatch.setattr(p, "_whisper_models", {})
    monkeypatch.setattr(p, "_load_whisper", lambda _: Item(transcribe=infer))
    provider = p.LocalWhisperProviders(settings)
    result = provider.transcribe_chunk(audio, 0, 122, owned_start=1, owned_end=121)
    assert selection.transcript(result["body"], 122).text == "Hello, world!"
    # Same tokens inside the caller's owned range still fail closed; no invented timing.
    with pytest.raises(p.ProviderFailure, match="whisper_transcription_failed"):
        provider.transcribe_chunk(audio, 0, 122)
