"""Phase 5: synthetic videos, actual PostgreSQL/FFmpeg, no paid provider calls."""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import fakeredis
import numpy as np
import pytest
import test_ai
import test_credits
import test_media
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from alembic import command as migrations
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import CreditReservation, CreditTransaction, ProviderUsage, SpendAttempt
from zoclip.credits.schemas import PolicyInput, QuoteInput
from zoclip.main import create_app
from zoclip.media import service as media_service
from zoclip.media import worker
from zoclip.media.cleanup import cleanup
from zoclip.media.models import Job, SourceVideo, StorageObject
from zoclip.media.schemas import ProcessInput
from zoclip.rendering import captions, engine, service
from zoclip.rendering.models import Clip, ClipRevision, RenderOutput
from zoclip.rendering.schemas import Preferences, RenderInput
from zoclip.rendering.tracking import smooth

financial_database = test_credits.concurrent_db
media = test_media.media
video_bytes = test_media.video_bytes
processing = test_ai.processing


@pytest.fixture
def selected(media, video_bytes, monkeypatch, request):
    factory, users, settings, storage = media
    video, _ = test_media.ready(media, video_bytes)
    settings = test_ai.configure(factory, users, settings)
    media = factory, users, settings, storage
    with factory() as db:
        quote = money.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=3, output_count=1, edit_count=getattr(request, "param", 0)),
            "render-quote",
        )
        job = media_service.process(
            db,
            users["alice"],
            ProcessInput(video_id=video, quote_id=quote.id),
            "render-process",
            settings,
            storage,
        )
        job_id = job.id
        db.commit()
    processing = media, video, job_id
    simulator = test_ai.Simulator()
    assert test_ai.drive(processing, monkeypatch, simulator) == ("SUGGESTIONS_READY", None)
    with factory() as db:
        limits = users["ai_limits"].model_copy(
            update={"render_cpu_seconds_per_output": 520, "storage_gb_days_per_output": 2}
        )
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Bounded local render fixtures"),
            "render-policy",
            users["admin"],
        )
        candidate = db.scalar(select(test_ai.ClipSuggestion))
        clip = service.create(db, users["alice"], candidate.id)
        clip_id = clip.id
        service.select_clips(db, users["alice"], job_id, [clip.id], "select", settings, storage)
        db.commit()
    return processing, clip_id, simulator


def render_selected(selected):
    ((factory, users, settings, storage), _, job_id), clip_id, _ = selected
    with factory() as db:
        generation = db.get(Job, job_id).generation
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.state == "COMPLETED", job.error_code
        return job_id


def test_end_to_end_actual_mp4_settles_once(selected):
    job_id = render_selected(selected)
    ((factory, users, settings, storage), _, _), clip_id, simulator = selected
    with factory() as db:
        job = db.get(Job, job_id)
        output = db.scalar(select(RenderOutput))
        assert output.state == "COMPLETE" and output.revision == 1
        assert (output.metadata_json["width"], output.metadata_json["height"]) == (720, 1280)
        assert output.metadata_json["framing"] == "center_fallback"
        assert abs(output.metadata_json["duration_ms"] - 2500) <= 100
        assert db.get(CreditReservation, job.reservation_id).state == "SETTLED"
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == 5
        generation = job.generation
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(RenderOutput)) == 1
    assert simulator.calls == ["deepgram", "gemini"]


@pytest.mark.parametrize("frame", ["center", "pad", "manual", "track"])
def test_real_encode_boundaries_audio_sync_and_frames(tmp_path, frame):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    prefs = Preferences(start_ms=417, end_ms=1833, frame=frame, focal_x=900)
    dest = tmp_path / "output.mp4"
    metadata = engine.render(
        Path("tests/fixtures/source.mp4").resolve(),
        dest,
        prefs,
        test_ai.dg_payload()["results"]["channels"][0]["alternatives"][0]["words"],
        settings,
        lambda: None,
    )
    assert abs(metadata["duration_ms"] - 1416) <= 100
    assert metadata["audio_codecs"] == ["aac"] and metadata["video_codec"] == "h264"
    assert metadata["width"] == 720 and metadata["height"] == 1280


def test_caption_relative_timing_overlap_and_injection():
    prefs = Preferences(start_ms=500, end_ms=2000)
    words = [
        {"word": "{\\pos(0,0)}evil\nDialogue: new", "start": 0.4, "end": 0.8},
        {"word": "اردو", "start": 0.7, "end": 1.1},
        {"word": "bad", "start": float("nan"), "end": 1.3},
        {"word": "bad", "start": 1.9, "end": 1.8},
        {"word": "later", "start": 1.8, "end": 2.5},
    ]
    normalized = captions.words_for(prefs, words)
    assert [(w[0], w[1]) for w in normalized] == [(0, 300), (300, 600), (1300, 1500)]
    result = captions.ass(prefs, words)
    assert r"\pos" not in result and "اردو" in result
    assert "0:00:00.00,0:00:00.30" in result and r"\c&H00FFFF&" in result


@pytest.mark.parametrize("preset", ["classic", "bold", "karaoke"])
def test_caption_presets_no_empty_intervals(preset):
    prefs = Preferences(start_ms=0, end_ms=2500, preset=preset)
    result = captions.ass(prefs, [{"word": "hello", "start": 0, "end": 0.5}])
    assert "Dialogue: 0,0:00:00.00,0:00:00.50" in result
    assert "Dialogue:" not in captions.ass(prefs.model_copy(update={"captions": False}), [])


@pytest.mark.parametrize(
    "updates",
    [
        {"start_ms": 2000, "end_ms": 1000},
        {"end_ms": 100},
        {"end_ms": 100000},
        {"frame": "crop=evil"},
        {"font": "font,filter=evil"},
        {"focal_x": 1001},
    ],
)
def test_preference_bounds(updates):
    with pytest.raises(ValidationError):
        Preferences.model_validate({"start_ms": 0, "end_ms": 2500, **updates})


def test_crop_smoothing_bounded_and_expression():
    positions = smooth([(0, 0), (2, 1), (4, 1), (6, 0)])
    last = 0.5
    for _, value in positions:
        assert 0 <= value <= 1 and abs(value - last) <= 0.1200001
        last = value
    assert "if(lt(t," in engine.crop(Preferences(start_ms=0, end_ms=2500), {"samples": positions})


def test_cancel_queued_releases_and_cleans_outputs(selected):
    ((factory, users, settings, storage), video, job_id), _, _ = selected
    with factory() as db:
        media_service.cancel_job(db, users["alice"], job_id)
        media_service.cancel_job(db, users["alice"], job_id)
        db.commit()
        assert db.get(SourceVideo, video).state == "READY"
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "RELEASE")
            )
            == 1
        )
    cleanup(factory, storage)
    with factory() as db:
        output = db.scalar(select(RenderOutput))
        assert output.state == "DELETED" and db.get(StorageObject, output.object_id).deleted


def test_failure_does_not_settle_or_destroy_source(selected, monkeypatch):
    ((factory, users, settings, storage), video, job_id), _, _ = selected
    monkeypatch.setattr(
        engine, "render", lambda *a: (_ for _ in ()).throw(ApiError(422, "render_invalid", "bad"))
    )
    with factory() as db:
        generation = db.get(Job, job_id).generation
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.state == "FAILED" and db.get(SourceVideo, video).state == "READY"
        assert db.get(CreditReservation, job.reservation_id).state == "RELEASED"
        assert not db.scalar(
            select(CreditTransaction.id).where(CreditTransaction.operation == "SETTLE")
        )
        assert not db.scalar(select(SpendAttempt.id).where(SpendAttempt.state == "HELD"))


def test_transient_retry_is_bounded(selected, monkeypatch):
    ((factory, users, settings, storage), _, job_id), _, _ = selected
    monkeypatch.setattr(engine, "render", lambda *a: (_ for _ in ()).throw(TimeoutError("fixture")))
    for i in range(3):
        with factory() as db:
            generation = db.get(Job, job_id).generation
        worker.run_job(job_id, generation, factory, settings, storage)
        with factory() as db:
            assert db.get(Job, job_id).state == ("FAILED" if i == 2 else "QUEUED")
    with factory() as db:
        assert db.scalar(select(RenderOutput)).failures == 3
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "RELEASE")
            )
            == 1
        )


def test_revision_conflict_and_paid_single_rerender_no_ai(selected):
    job_id = render_selected(selected)
    ((factory, users, settings, storage), _, _), clip_id, simulator = selected
    with factory() as db:
        prefs = Preferences.model_validate(service.revision(db, db.get(Clip, clip_id)).preferences)
        prefs = prefs.model_copy(update={"start_ms": 250, "end_ms": 2000, "preset": "bold"})
        service.edit(db, users["alice"], clip_id, 1, prefs)
        db.commit()
    with factory() as db, pytest.raises(ApiError, match="Reload"):
        service.edit(db, users["alice"], clip_id, 1, prefs)
    with factory() as db, pytest.raises(ApiError) as error:
        service.rerender(
            db, users["alice"], clip_id, RenderInput(revision=2), "extra", settings, storage
        )
    assert error.value.code == "quote_required"
    with factory() as db:
        quote = money.make_quote(
            db, users["alice"], QuoteInput(source_seconds=3, output_count=1), "extra-quote"
        )
        rerender = service.rerender(
            db,
            users["alice"],
            clip_id,
            RenderInput(revision=2, quote_id=quote.id),
            "extra",
            settings,
            storage,
        )
        extra_id = rerender.id
        db.commit()
    worker.run_job(extra_id, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, extra_id).state == "COMPLETED"
        assert db.get(Job, job_id).state == "COMPLETED"
        assert db.scalar(select(func.count()).select_from(RenderOutput)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 2
        )
        assert db.scalar(select(func.count()).select_from(ClipRevision)) == 2
    assert simulator.calls == ["deepgram", "gemini"]


def test_concurrent_selection_replay_and_owner_isolation(selected):
    ((factory, users, settings, storage), _, job_id), clip_id, _ = selected
    barrier = Barrier(2)

    def select_again():
        barrier.wait(timeout=5)
        with factory() as db:
            result = service.select_clips(
                db, users["alice"], job_id, [clip_id], "select", settings, storage
            )
            db.commit()
            return result.id

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(lambda _: select_again(), range(2))) == [job_id, job_id]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(RenderOutput)) == 1
    with factory() as db, pytest.raises(ApiError) as error:
        service.select_clips(db, users["bob"], job_id, [clip_id], "stolen", settings, storage)
    assert error.value.status == 404


def test_cancel_during_encode_terminates_process(tmp_path):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    checks = 0

    def heartbeat():
        nonlocal checks
        checks += 1
        raise ApiError(409, "job_canceled", "fixture cancellation")

    with pytest.raises(ApiError) as error:
        engine.command(
            [os.sys.executable, "-c", "import time; time.sleep(30)"],
            settings,
            tmp_path,
            time.monotonic() + 10,
            heartbeat,
        )
    assert error.value.code == "job_canceled" and checks == 1


def test_delete_revokes_and_erases_revision_text(selected):
    render_selected(selected)
    ((factory, users, settings, storage), video, _), clip_id, _ = selected
    with factory() as db:
        media_service.delete_video(db, users["alice"], video)
        db.commit()
    cleanup(factory, storage)
    with factory() as db:
        assert db.get(Clip, clip_id).suggestion_id is None
        assert not db.scalar(select(ClipRevision.id))
        assert db.scalar(select(RenderOutput)).state == "DELETED"


@pytest.mark.parametrize("selected", [1], indirect=True)
def test_prepaid_edit_is_bounded_and_has_no_second_charge(selected):
    render_selected(selected)
    ((factory, users, settings, storage), _, _), clip_id, _ = selected
    with factory() as db:
        prefs = Preferences.model_validate(service.revision(db, db.get(Clip, clip_id)).preferences)
        service.edit(db, users["alice"], clip_id, 1, prefs.model_copy(update={"preset": "classic"}))
        job = service.rerender(
            db, users["alice"], clip_id, RenderInput(revision=2), "included", settings, storage
        )
        extra_id = job.id
        assert job.reservation_id is None and job.checkpoint["included_edit"]
        db.commit()
    worker.run_job(extra_id, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, extra_id).state == "COMPLETED"
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 1
        )
        service.edit(db, users["alice"], clip_id, 2, prefs)
        db.commit()
    with factory() as db, pytest.raises(ApiError) as error:
        service.rerender(
            db, users["alice"], clip_id, RenderInput(revision=3), "exhausted", settings, storage
        )
    assert error.value.code == "quote_required"


def test_recover_expired_render_lease_preserves_costs(selected):
    ((factory, users, settings, storage), _, job_id), _, _ = selected
    with factory() as db:
        generation = db.get(Job, job_id).generation
        worker.claim(db, job_id, generation)
        job = db.get(Job, job_id)
        rate, _, units = service.budget(db, settings)
        attempt, fresh = money.admit_spend(
            db, users["alice"], job.reservation_id, rate, units, "lost-render"
        )
        assert fresh
        attempt_id = attempt.id
        job.checkpoint = {**job.checkpoint, "render_attempt": str(attempt.id)}
        job.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert worker.recover(factory, storage) == 1
    with factory() as db:
        assert db.get(SpendAttempt, attempt_id).state == "RECORDED"
        assert db.get(Job, job_id).state == "QUEUED"
        assert db.get(Job, job_id).lease_token is None
        assert not db.scalar(
            select(CreditTransaction.id).where(CreditTransaction.operation == "SETTLE")
        )
    render_selected(selected)


def test_crash_promoted_output_reuses_file_without_encode(selected, monkeypatch):
    ((factory, users, settings, storage), _, _), clip_id, _ = selected
    with factory() as db:
        output = db.scalar(select(RenderOutput))
        video = db.get(SourceVideo, db.get(Clip, clip_id).video_id)
        prefs = Preferences.model_validate(service.revision(db, db.get(Clip, clip_id)).preferences)
        source, target = storage.path(video.object_id), storage.path(output.object_id)
    engine.render(source, target, prefs, [], settings, lambda: None)
    monkeypatch.setattr(engine, "render", lambda *a: pytest.fail("Must reuse promoted file"))
    render_selected(selected)
    with factory() as db:
        assert (
            db.scalar(select(RenderOutput)).metadata_json["framing"] == "recovered_verified_output"
        )


def test_private_api_revision_headers_and_revocation(selected):
    render_selected(selected)
    ((factory, users, settings, storage), video_id, _), clip_id, _ = selected
    application = create_app(settings.model_copy(update={"cookie_secure": False}))
    original_engine = application.state.engine
    application.state.session_factory = factory
    application.state.redis = fakeredis.FakeRedis()
    with TestClient(application, base_url="http://localhost:8000") as client:
        headers = test_credits.authenticate(client, application, users["alice"])
        base = f"/api/v1/clips/{clip_id}"
        detail = client.get(base)
        assert detail.status_code == 200
        assert client.get("/api/v1/clips").status_code == 200
        assert len(client.get(base + "/renders").json()) == 1
        downloaded = client.get(base + "/download")
        assert downloaded.status_code == 200 and downloaded.content[4:8] == b"ftyp"
        assert (
            client.patch(base, json=detail.json()["preferences"], headers=headers).status_code
            == 422
        )
        assert (
            client.patch(
                base, json=detail.json()["preferences"], headers=headers | {"If-Match": '"1"'}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                base, json=detail.json()["preferences"], headers=headers | {"If-Match": '"1"'}
            ).status_code
            == 409
        )
        assert client.get(base + "/download").status_code == 404
        assert client.get(base + "/download?revision=1").status_code == 200
        test_credits.authenticate(client, application, users["bob"])
        for path in (base, base + "/renders", base + "/download?revision=1"):
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/clips").json() == []
        headers = test_credits.authenticate(client, application, users["alice"])
        assert client.delete(f"/api/v1/videos/{video_id}", headers=headers).status_code == 204
        assert client.get(base + "/download?revision=1").status_code == 409
    original_engine.dispose()


def test_missing_render_estimate_fails_before_work(selected, monkeypatch):
    ((factory, users, settings, storage), _, job_id), _, _ = selected
    with factory() as db:
        limits = users["ai_limits"].model_copy(update={"render_cpu_seconds_per_output": 1})
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Too small fixture estimate"),
            "tiny-render",
            users["admin"],
        )
        generation = db.get(Job, job_id).generation
        db.commit()
    monkeypatch.setattr(engine, "render", lambda *a: pytest.fail("No unbudgeted encode"))
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.state == "FAILED" and job.error_code == "render_estimate_unconfigured"
        assert db.get(CreditReservation, job.reservation_id).state == "RELEASED"


def test_paid_provider_cannot_use_prepaid_render_permission(selected):
    ((factory, users, settings, storage), _, job_id), _, _ = selected
    with factory() as db, pytest.raises(ApiError) as error:
        job = db.get(Job, job_id)
        money.admit_spend(
            db,
            users["alice"],
            job.reservation_id,
            users["rates"]["gemini_input"],
            1,
            "forbidden",
            prepaid_render_job=job_id,
        )
    assert error.value.code == "reservation_final"


def test_nonkeyframe_cut_content_audio_and_burned_captions(tmp_path):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    source = tmp_path / "markers.mp4"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-nostdin",
            "-filter_complex_threads",
            "1",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1:sample_rate=48000",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-g",
            "120",
            "-c:a",
            "aac",
            "-f",
            "mp4",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    prefs = Preferences(start_ms=1250, end_ms=1950, frame="center", captions=False)
    dest = tmp_path / "cut.mp4"
    engine.render(source, dest, prefs, [], settings, lambda: None)
    pixel = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(dest),
            "-vf",
            "scale=1:1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        timeout=10,
    ).stdout
    assert pixel[2] > 180 and pixel[0] < 30
    audio = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(dest),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        timeout=10,
    ).stdout
    samples = np.frombuffer(audio, dtype="<i2").astype(float)
    assert np.sqrt(np.mean(samples * samples)) > 500
    spectrum = abs(np.fft.rfft(samples))
    frequency = np.fft.rfftfreq(len(samples), 1 / 8000)[int(np.argmax(spectrum))]
    assert abs(frequency - 880) < 10
    captioned = tmp_path / "captioned.mp4"
    engine.render(
        source,
        captioned,
        prefs.model_copy(update={"captions": True}),
        [{"word": "HELLO", "start": 1.25, "end": 1.95}],
        settings,
        lambda: None,
    )

    def band(path):
        return subprocess.run(
            [
                settings.ffmpeg_binary,
                "-v",
                "error",
                "-ss",
                "0.3",
                "-i",
                str(path),
                "-vf",
                "crop=640:200:40:900,scale=160:50",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            stdout=subprocess.PIPE,
            timeout=10,
        ).stdout

    assert band(dest) != band(captioned)


@pytest.mark.parametrize("dimensions", ["90x160", "90x90"])
def test_portrait_square_low_resolution_fallback(tmp_path, dimensions):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    source = tmp_path / "small.mp4"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            "tests/fixtures/source.mp4",
            "-vf",
            "scale=" + dimensions.replace("x", ":"),
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-t",
            "1",
            str(source),
        ],
        check=True,
        timeout=15,
    )
    result = engine.render(
        source.resolve(),
        tmp_path / "vertical.mp4",
        Preferences(start_ms=0, end_ms=750, frame="pad"),
        [],
        settings,
        lambda: None,
    )
    assert (result["width"], result["height"]) == (720, 1280)


def test_original_audio_offset_is_preserved(tmp_path):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    source = tmp_path / "offset.mp4"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=30:d=2",
            "-itsoffset",
            "0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1.5:sample_rate=48000",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        timeout=15,
    )
    destination = tmp_path / "offset-cut.mp4"
    engine.render(
        source,
        destination,
        Preferences(start_ms=0, end_ms=1500, captions=False),
        [],
        settings,
        lambda: None,
    )
    raw = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(destination),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        check=True,
        timeout=10,
    ).stdout
    samples = np.frombuffer(raw, dtype="<i2").astype(float)
    assert np.sqrt(np.mean(samples[:1600] ** 2)) < 5
    assert np.sqrt(np.mean(samples[6400:8000] ** 2)) > 500


def test_render_claims_separate_from_ai_but_serialized(selected):
    ((factory, users, settings, storage), video, job_id), _, _ = selected
    with factory() as db:
        generation = db.get(Job, job_id).generation
        assert worker.claim(db, job_id, generation)
        render_job = media_service.queue_job(
            db, users["alice"], video, "RENDER", "parallel-render", {}, "0" * 64
        )
        render_job.checkpoint = {"render_selection": True}
        ai_job = media_service.queue_job(
            db, users["alice"], video, "VALIDATE", "parallel-ai", {}, "1" * 64
        )
        db.commit()
        render_id, ai_id = render_job.id, ai_job.id
    with factory() as db:
        assert worker.claim(db, render_id, 0) is None
        assert worker.claim(db, ai_id, 0) is not None
        db.commit()


def test_tracking_runs_in_real_bounded_subprocess(tmp_path):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:test@localhost/test"
    )
    data = engine.command(
        [
            os.sys.executable,
            "-m",
            "zoclip.rendering.tracking",
            str(Path("tests/fixtures/source.mp4").resolve()),
            "0",
            "2.5",
        ],
        settings,
        tmp_path,
        time.monotonic() + 20,
        lambda: None,
        capture=True,
    )
    assert json.loads(data) == {"mode": "center_fallback", "samples": [], "faces_found": 0}


def test_live_render_cancellation_acknowledges_before_release(selected, monkeypatch):
    ((factory, users, settings, storage), video, job_id), _, _ = selected

    def canceled_render(source, destination, prefs, words, settings, heartbeat):
        with factory() as db:
            result = media_service.cancel_job(db, users["alice"], job_id)
            assert result.state == "CANCEL_REQUESTED"
            assert db.get(CreditReservation, result.reservation_id).state == "HELD"
            db.commit()
        time.sleep(1.05)
        heartbeat()
        pytest.fail("Cancellation must interrupt rendering")

    monkeypatch.setattr(engine, "render", canceled_render)
    with factory() as db:
        generation = db.get(Job, job_id).generation
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.state == "CANCELED"
        assert db.get(CreditReservation, job.reservation_id).state == "RELEASED"
        assert db.get(SourceVideo, video).state == "READY"


@pytest.mark.parametrize("selected", [1], indirect=True)
def test_refund_disables_unused_prepaid_edits(selected):
    render_selected(selected)
    ((factory, users, settings, storage), _, _), clip_id, _ = selected
    with factory() as db:
        charge = db.scalar(select(CreditTransaction).where(CreditTransaction.operation == "SETTLE"))
        money.refund(
            db,
            users["alice"],
            charge.id,
            -charge.reserved_delta,
            "refund-render",
            users["admin"],
            "Fixture full render refund",
        )
        prefs = Preferences.model_validate(service.revision(db, db.get(Clip, clip_id)).preferences)
        service.edit(db, users["alice"], clip_id, 1, prefs)
        db.commit()
    with factory() as db, pytest.raises(ApiError) as error:
        service.rerender(
            db,
            users["alice"],
            clip_id,
            RenderInput(revision=2),
            "refunded-prepaid",
            settings,
            storage,
        )
    assert error.value.code == "quote_required"


def test_populated_render_migration_refuses_downgrade(selected):
    factory = selected[0][0][0]
    with factory().get_bind().begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Refusing to erase render"):
            migrations.downgrade(config, "91731e381b3a")
