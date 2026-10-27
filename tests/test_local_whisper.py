"""Fake local inference only: ordinary tests never download a model or call providers."""

import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as Item

import httpx
import pytest
from pydantic import ValidationError

from zoclip.ai import providers as p
from zoclip.ai import selection, worker
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


@pytest.fixture
def local(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused:unused@localhost/whisper_test",
        media_root=str(tmp_path),
        whisper_model_path=str(tmp_path / "model"),
    )
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\0\0" * 40000)
    calls = []

    class Model:
        def transcribe(self, path, **options):
            assert options == {
                "language": "en",
                "beam_size": 1,
                "vad_filter": True,
                "word_timestamps": True,
            }

            def segments():
                calls.append("inference")
                yield Item(
                    words=[
                        Item(word=" Hello,", start=0.2, end=0.6, probability=0.98),
                        Item(word=" world!", start=0.8, end=1.4, probability=0.9),
                    ]
                )

            return segments(), Item(duration=2.5, duration_after_vad=1.2)

    def load(s):
        calls.append("load")
        return Model()

    class Pipeline:
        """Fake BatchedInferencePipeline: records the batch, delegates the rest."""

        def __init__(self, model):
            self.model = model

        def transcribe(self, audio, **options):
            batch = options.pop("batch_size")
            assert batch == settings.whisper_batch_size and batch > 0
            return self.model.transcribe(audio, **options)

    def blocked(*args, **kwargs):
        pytest.fail("Local transcription attempted HTTP")

    monkeypatch.setattr(p, "_load_whisper", load)
    monkeypatch.setattr(p, "_load_batched_pipeline", Pipeline)
    monkeypatch.setattr(p, "_whisper_models", {})
    monkeypatch.setattr(p, "_batched_pipelines", {})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    return settings, audio, calls, Model


def test_shape_timestamps_punctuation_confidence_and_unchanged_contract(local):
    settings, audio, calls, _ = local
    result = p.LocalWhisperProviders(settings).transcribe(audio)
    assert result["status"] == 200 and calls == ["load", "inference"]
    data = selection.transcript(result["body"], 2.5)
    assert data.text == "Hello, world!"
    assert data.duration_seconds == 2.5 and data.utterances == []
    assert [(w.start, w.end) for w in data.words] == [(0.2, 0.6), (0.8, 1.4)]
    assert [w.confidence for w in data.words] == [0.98, 0.9]
    assert all(w.speaker == 0 for w in data.words)


def test_lazy_model_reuse_across_adapter_instances(local):
    settings, audio, calls, _ = local
    provider = p.LocalWhisperProviders(settings)
    assert not calls
    provider.transcribe(audio)
    p.LocalWhisperProviders(settings).transcribe(audio)
    assert calls == ["load", "inference", "inference"]


def test_empty_speech_is_not_fabricated(local, monkeypatch):
    settings, audio, _, model = local
    monkeypatch.setattr(model, "transcribe", lambda *a, **kw: (iter([]), Item(duration=2.5)))
    result = p.LocalWhisperProviders(settings).transcribe(audio)
    data = selection.transcript(result["body"], 2.5)
    assert data.words == [] and data.text == "" and data.duration_seconds == 2.5


def test_zero_length_token_preserves_text_without_inventing_timing(local, monkeypatch):
    settings, audio, _, model = local
    words = [
        Item(word=" Hello", start=0.2, end=0.6, probability=0.98),
        Item(word=",", start=0.6, end=0.6, probability=0.95),
        Item(word=" a", start=0.6, end=0.6, probability=0.96),
        Item(word=" friend!", start=0.6, end=1.0, probability=0.9),
    ]
    monkeypatch.setattr(model, "transcribe", lambda *a, **kw: (iter([Item(words=words)]), Item()))
    data = selection.transcript(p.LocalWhisperProviders(settings).transcribe(audio)["body"], 2.5)
    assert data.text == "Hello, a friend!"
    assert [(w.start, w.end) for w in data.words] == [(0.2, 0.6), (0.6, 1.0)]
    assert data.words[0].confidence == 0.95


def test_unanchored_zero_length_token_fails_closed(local, monkeypatch):
    settings, audio, _, model = local
    monkeypatch.setattr(
        model,
        "transcribe",
        lambda *a, **kw: (
            iter([Item(words=[Item(word="unknown", start=0.2, end=0.2, probability=0.9)])]),
            Item(),
        ),
    )
    with pytest.raises(p.ProviderFailure):
        p.LocalWhisperProviders(settings).transcribe(audio)


def test_zero_length_token_at_following_word_boundary(local, monkeypatch):
    settings, audio, _, model = local
    words = [
        Item(word=" Hello", start=0.2, end=0.5, probability=0.98),
        Item(word=" a", start=0.6, end=0.6, probability=0.96),
        Item(word=" friend!", start=0.6, end=1.0, probability=0.9),
    ]
    monkeypatch.setattr(model, "transcribe", lambda *a, **kw: (iter([Item(words=words)]), Item()))
    data = selection.transcript(p.LocalWhisperProviders(settings).transcribe(audio)["body"], 2.5)
    assert data.text == "Hello a friend!"
    assert [(w.start, w.end) for w in data.words] == [(0.2, 0.5), (0.6, 1.0)]


@pytest.mark.parametrize("kind", ["missing", "malformed", "truncated", "empty"])
def test_invalid_audio_fails_before_loading(local, kind):
    settings, audio, calls, _ = local
    if kind == "missing":
        audio.unlink()
    elif kind == "malformed":
        audio.write_bytes(b"not audio")
    elif kind == "truncated":
        audio.write_bytes(audio.read_bytes()[:-8])
    else:
        with wave.open(str(audio), "wb") as f:
            f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
    with pytest.raises(p.ProviderFailure, match="^whisper_invalid_audio$") as error:
        p.LocalWhisperProviders(settings).transcribe(audio)
    assert str(audio) not in str(error.value) and calls == []


@pytest.mark.parametrize("stage", ["load", "transcribe", "generator"])
def test_failures_are_private_and_never_fall_back(local, monkeypatch, stage):
    settings, audio, _, model = local

    def fail(*a, **kw):
        raise RuntimeError("private/audio.wav secret-value")

    if stage == "load":
        monkeypatch.setattr(p, "_load_whisper", fail)
    elif stage == "transcribe":
        monkeypatch.setattr(model, "transcribe", fail)
    else:

        def generated():
            yield Item(words=[])
            fail()

        monkeypatch.setattr(model, "transcribe", lambda *a, **kw: (generated(), Item()))
    with pytest.raises(p.ProviderFailure, match="^whisper_transcription_failed$") as error:
        p.LocalWhisperProviders(settings).transcribe(audio)
    assert error.value.__suppress_context__ and "private" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", float("nan")),
        ("end", 3.0),
        ("end", 0.1),
        ("probability", float("inf")),
        ("probability", -0.1),
        ("probability", True),
    ],
)
def test_invalid_model_output_rejected(local, monkeypatch, field, value):
    settings, audio, _, model = local
    word = Item(word="hello", start=0.2, end=0.5, probability=0.9)
    setattr(word, field, value)
    monkeypatch.setattr(model, "transcribe", lambda *a, **kw: (iter([Item(words=[word])]), Item()))
    with pytest.raises(p.ProviderFailure):
        p.LocalWhisperProviders(settings).transcribe(audio)


def test_default_whisper_explicit_deepgram_and_unknown(local):
    settings, _, _, _ = local
    assert settings.transcription_provider == "whisper"
    assert type(worker.default_providers(settings)) is p.LocalWhisperProviders
    fallback = Settings(
        _env_file=None, **(settings.model_dump() | {"transcription_provider": "deepgram"})
    )
    assert type(worker.default_providers(fallback)) is p.HTTPProviders
    assert p.LocalWhisperProviders.analyze is p.HTTPProviders.analyze
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | {"transcription_provider": "unknown"}))
    with pytest.raises(ApiError):
        worker.default_providers(settings.model_copy(update={"transcription_provider": "unknown"}))


@pytest.mark.parametrize(
    "key,value",
    [
        ("whisper_model", "large-v3"),
        ("whisper_device", "cuda"),
        ("whisper_compute_type", "float16"),
    ],
)
def test_unreviewed_configuration_rejected(local, key, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(local[0].model_dump() | {key: value}))


def test_missing_model_files_never_download(local):
    with pytest.raises(p.ProviderFailure, match="whisper_model_unavailable"):
        p.check_whisper_files(local[0])


def test_installed_decoder_accepts_extracted_pcm_without_model_download(local):
    # Catch the real PyAV API mismatch which a fake model cannot exercise.
    from faster_whisper.audio import decode_audio

    samples = decode_audio(str(local[1]), sampling_rate=16000)
    assert len(samples) == 40000 and samples.dtype.name == "float32"


def test_threads_bounded_parallel_and_reuse_models(local, monkeypatch):
    settings, audio, calls, model = local
    settings.whisper_parallelism = 2  # mechanism test; production default is 1
    original = model.transcribe
    lock = threading.Lock()
    active = 0
    peak = 0

    def transcribe(self, *a, **kw):
        def segments():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            yield from original(self, *a, **kw)[0]
            with lock:
                active -= 1

        return segments(), Item()

    monkeypatch.setattr(model, "transcribe", transcribe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: p.LocalWhisperProviders(settings).transcribe(audio), range(2))
        )
    assert all(r["status"] == 200 for r in results)
    assert peak == 2  # the configured slots transcribe truly in parallel
    assert calls.count("load") == 2  # one model instance per slot, then reused


def test_all_slots_busy_fails_closed(local, monkeypatch):
    settings, audio, calls, model = local
    settings = settings.model_copy(update={"whisper_parallelism": 1})
    original = model.transcribe
    started = threading.Event()
    release = threading.Event()

    def transcribe(self, *a, **kw):
        def segments():
            started.set()
            assert release.wait(timeout=5)
            yield from original(self, *a, **kw)[0]

        return segments(), Item()

    monkeypatch.setattr(model, "transcribe", transcribe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: p.LocalWhisperProviders(settings).transcribe(audio))
        assert started.wait(timeout=5)
        with pytest.raises(p.ProviderFailure):
            p.LocalWhisperProviders(settings).transcribe(audio)
        release.set()
        assert future.result(timeout=5)["status"] == 200
