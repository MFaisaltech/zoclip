"""Customer-confirmed automatic exports: real FFmpeg, isolated PostgreSQL, mock AI."""

import json
import math
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import test_ai
import test_media
from sqlalchemy import func, select

from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import (
    CreditReservation,
    CreditTransaction,
    SystemLimits,
)
from zoclip.credits.schemas import PolicyInput, QuoteInput
from zoclip.media import service
from zoclip.media.models import Job
from zoclip.media.schemas import LinkImportInput, ProcessInput
from zoclip.ops.catalog import install
from zoclip.rendering.models import RenderOutput

financial_database = test_ai.financial_database
media = test_media.media


@pytest.mark.parametrize("seconds,outputs", [(24, 1), (24.5, 1), (120, 1), (60, 3)])
@pytest.mark.parametrize("input_kind", ["upload", "youtube"])
def test_upload_generate_render_mp4_without_manual_selection(
    media, monkeypatch, tmp_path, seconds, outputs, input_kind
):
    factory, users, settings, storage = media
    source = tmp_path / "customer-source.mp4"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        timeout=90,
    )
    if input_kind == "youtube":
        # Actual network download is verified separately in the isolated worker
        # smoke. Here the transport boundary supplies owned synthetic media.
        def downloaded(url, dest, settings, progress):
            data = source.read_bytes()
            dest.write_bytes(data)
            return len(data)

        monkeypatch.setattr(test_media.worker, "download_youtube", downloaded)
        with factory() as db:
            imported = service.import_link(
                db,
                users["alice"],
                LinkImportInput(url="https://youtu.be/aqz-KE-bpKQ", rights_attested=True),
                "release-link",
                settings,
                storage,
            )
            imported_id, video = imported.id, imported.video_id
            db.commit()
        test_media.worker.run_job(imported_id, 0, factory, settings, storage)
    else:
        video, _ = test_media.ready(media, source.read_bytes())
    settings = test_ai.configure(factory, users, settings)
    settings = settings.model_copy(update={"ai_min_clip_seconds": 15})
    with factory() as db:
        limits = users["ai_limits"].model_copy(
            update={
                "render_cpu_seconds_per_output": 520,
                "storage_gb_days_per_output": 2,
            }
        )
        money.configure_policy(
            db,
            PolicyInput(limits=limits, reason="Isolated real media regression"),
            "release-render",
            users["admin"],
        )
        quote = money.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=math.ceil(seconds), output_count=outputs),
            "release-quote",
        )
        request = ProcessInput(video_id=video, quote_id=quote.id, auto_render=True)
        job = service.process(db, users["alice"], request, "release-process", settings, storage)
        assert (
            service.process(db, users["alice"], request, "release-process", settings, storage).id
            == job.id
        )
        with pytest.raises(ApiError, match="idempotency_conflict"):
            service.process(
                db,
                users["alice"],
                request.model_copy(update={"auto_render": False}),
                "release-process",
                settings,
                storage,
            )
        job_id, reservation_id = job.id, job.reservation_id
        db.commit()
    words = [
        {"word": "example", "start": i / 2, "end": (i + 1) / 2, "confidence": 0.95}
        for i in range(int(seconds * 2))
    ]
    dg = {
        "metadata": {"duration": seconds},
        "results": {"channels": [{"alternatives": [{"confidence": 0.95, "words": words}]}]},
    }
    simulator = test_ai.Simulator(
        dg=dg,
        gemini=test_ai.gemini_payload(
            [test_ai.moment(start_sec=i * 20, end_sec=i * 20 + 20) for i in range(outputs)]
        ),
    )
    configured = factory, users, settings, storage
    assert test_ai.drive((configured, video, job_id), monkeypatch, simulator) == ("COMPLETED", None)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(RenderOutput)
                .where(RenderOutput.job_id == job_id, RenderOutput.state == "COMPLETE")
            )
            == outputs
        )
        output = db.scalar(select(RenderOutput).where(RenderOutput.job_id == job_id))
        assert output.state == "COMPLETE"
        assert 15000 <= output.metadata_json["duration_ms"] <= 30000
        assert (output.metadata_json["width"], output.metadata_json["height"]) == (720, 1280)
        assert db.get(CreditReservation, reservation_id).state == "SETTLED"
        output_path = storage.path(output.object_id)
        assert output_path.stat().st_size > 1000
        result = subprocess.run(
            [
                settings.ffprobe_binary,
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        streams = json.loads(result.stdout)["streams"]
        assert {stream["codec_type"] for stream in streams} == {"audio", "video"}
        assert abs(float(streams[0]["duration"]) - float(streams[1]["duration"])) < 0.15
        subprocess.run(
            [settings.ffmpeg_binary, "-v", "error", "-i", str(output_path), "-f", "null", "-"],
            check=True,
            capture_output=True,
            timeout=45,
        )
        # Keep a shareable synthetic output as acceptance evidence, outside private DB state.
        evidence = Path(os.environ.get("ZOCLIP_RELEASE_EVIDENCE", "var/release-evidence"))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f"source-{seconds}s-clip.mp4").write_bytes(output_path.read_bytes())
        (evidence / f"source-{seconds}s-metadata.json").write_text(
            json.dumps(output.metadata_json, indent=2), encoding="utf-8"
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 1
        )
        generation = db.get(Job, job_id).generation
    test_media.worker.run_job(job_id, generation, factory, settings, storage)
    assert simulator.calls.count("deepgram") == 1
    assert simulator.calls.count("gemini") == len(
        list(
            test_ai.selection.chunks(
                [test_ai.Word(**{**w, "punctuated_word": w["word"]}) for w in words], settings
            )
        )
    )


def test_catalog_provisions_real_quote_terms_without_grants(financial_database):
    factory, users = financial_database
    from zoclip.core.config import Settings

    config = Settings(
        _env_file=None,
        app_env="production",
        private_staging=True,
        allowed_hosts=["api.example.com"],
        registration_enabled=False,
        email_mode="disabled",
        payment_provider="disabled",
        staging_site_domain="example.com",
        public_app_url="https://app.example.com",
        api_public_url="https://api.example.com",
        database_url=factory.kw["bind"].url.render_as_string(hide_password=False),
    )
    catalog = json.loads(Path("deploy/staging-catalog.json").read_text())
    with factory() as db:
        db.get(SystemLimits, 1).breaker = True
        before = db.scalar(select(func.count()).select_from(CreditTransaction))
        first = install(db, config, users["admin"], catalog)
        assert install(db, config, users["admin"], catalog) == first
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == before
        preview = money.preview_quote(
            db, users["alice"], QuoteInput(source_seconds=26, output_count=1), config
        )
        assert preview.credits == 50 and not preview.processing_enabled
        quote = money.make_quote(db, users["alice"], preview.request, str(uuid4()), production=True)
        assert quote.credits == 50
        money.adjust(
            db,
            users["alice"],
            100,
            "fixture-balance",
            users["admin"],
            "Fictional local test balance",
            grant=True,
        )
        with pytest.raises(ApiError, match="spending_disabled"):
            money.reserve(db, users["alice"], quote.id, uuid4(), str(uuid4()), production=True)
        assert db.get(SystemLimits, 1).breaker is True
