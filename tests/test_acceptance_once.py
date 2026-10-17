"""One-shot guard tests. No paid calls, schema resets, drops or data deletion."""

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.ai import acceptance
from zoclip.ai import worker as ai
from zoclip.ai.providers import ProviderFailure
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.media import worker
from zoclip.media.models import Job, SourceVideo


def binding(job, settings, digest="a" * 64):
    return {
        "version": 1,
        "owner": str(job.user_id),
        "job": str(job.id),
        "video": str(job.video_id),
        "source_sha256": digest,
        "configuration": acceptance.configuration(settings),
        "dispatches": {},
    }


def test_consumed_slot_survives_serialization_and_same_request_id_restart():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://offline/offline")
    job = SimpleNamespace(id=uuid4(), user_id=uuid4(), video_id=uuid4(), checkpoint={})
    job.checkpoint[acceptance.MARKER] = binding(job, settings)
    request = uuid4()
    acceptance.consume(job, settings, "deepgram", request, "a" * 64)
    job.checkpoint = json.loads(json.dumps(job.checkpoint))
    for request_id in (request, uuid4()):
        with pytest.raises(ApiError) as error:
            acceptance.consume(job, settings, "deepgram", request_id, "a" * 64)
        assert error.value.code == "acceptance_request_consumed"
    acceptance.consume(job, settings, "gemini", uuid4(), "a" * 64)
    assert set(job.checkpoint[acceptance.MARKER]["dispatches"]) == {"deepgram", "gemini"}


@pytest.mark.parametrize(
    "field", ["job", "owner", "video", "source_sha256", "configuration", "dispatches"]
)
def test_changed_binding_fails_closed(field):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://offline/offline")
    job = SimpleNamespace(id=uuid4(), user_id=uuid4(), video_id=uuid4(), checkpoint={})
    value = binding(job, settings)
    value[field] = None
    job.checkpoint[acceptance.MARKER] = value
    with pytest.raises(ApiError) as error:
        acceptance.consume(job, settings, "deepgram", uuid4(), "a" * 64)
    assert error.value.code == "acceptance_binding_invalid"


def test_ordinary_jobs_do_not_acquire_acceptance_limits():
    job = SimpleNamespace(checkpoint={"ordinary": True})
    acceptance.consume(job, None, "deepgram", uuid4(), "a" * 64)
    assert job.checkpoint == {"ordinary": True}


@pytest.fixture
def guarded_processing(tmp_path, monkeypatch):
    """Forward migrate a NEW schema in the separate mock DB; preserve it afterward."""
    import test_ai
    import test_credits
    import test_media

    url = os.environ.get("ZOCLIP_ACCEPTANCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Separate mock DB opt-in required; never use readiness/live data")
    parsed = make_url(url)
    if (
        (parsed.host, parsed.port) != ("127.0.0.1", 55439)
        or not (parsed.database or "").startswith("zoclip_mock_")
        or not parsed.database.endswith("_test")
    ):
        pytest.fail("Only the saved isolated mock DB is allowed")
    schema = "acceptance_test_" + uuid4().hex
    root = create_engine(url, hide_parameters=True)
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        pool_size=3,
        max_overflow=0,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC"},
    )
    try:
        config = Config("alembic.ini")
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        factory = sessionmaker(engine, expire_on_commit=False)
        users = test_credits.seed(factory)
        # Reuse fixture helpers, never their reset/drop fixtures.
        media = test_media.media.__wrapped__((factory, users), tmp_path, monkeypatch)
        video, _ = test_media.ready(media, Path("tests/fixtures/source.mp4").read_bytes())
        settings = test_ai.configure(factory, users, media[2])
        settings = settings.model_copy(update={"ai_max_chunks": 1, "ai_max_candidates": 1})
        media = factory, users, settings, media[3]
        job_id = test_media.process_job(media, video)
        with factory() as db:
            job = db.get(Job, job_id)
            digest = db.get(SourceVideo, video).metadata_json["sha256"]
            job.checkpoint = {**job.checkpoint, acceptance.MARKER: binding(job, settings, digest)}
            db.commit()
        yield media, job_id
    finally:
        engine.dispose()
        root.dispose()  # Preserve the new schema/evidence; no DROP or downgrade.


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "deepgram-429",
        "deepgram-timeout",
        "deepgram-crash",
        "gemini-429",
        "gemini-timeout",
        "gemini-crash",
    ],
)
def test_worker_guard_before_mock_dispatch_and_restart(guarded_processing, monkeypatch, outcome):
    import test_ai

    (factory, users, settings, storage), job_id = guarded_processing
    calls = []
    failed_provider, failure = outcome.split("-", 1) if "-" in outcome else (None, None)

    def fail(provider):
        if provider != failed_provider:
            return None
        if failure == "429":
            return {"status": 429, "body": {}}
        if failure == "timeout":
            raise ProviderFailure("synthetic_timeout")
        raise KeyboardInterrupt("simulated abrupt worker death")

    class MockProviders(test_ai.Simulator):
        def transcribe(self, path):
            # Persisted slot must exist in a DIFFERENT database connection already.
            with factory() as db:
                checkpoint = db.get(Job, job_id).checkpoint
                assert "deepgram" in checkpoint[acceptance.MARKER]["dispatches"]
            calls.append("deepgram")
            return fail("deepgram") or super().transcribe(path)

        def analyze(self, body):
            with factory() as db:
                assert "gemini" in db.get(Job, job_id).checkpoint[acceptance.MARKER]["dispatches"]
            calls.append("gemini")
            return fail("gemini") or super().analyze(body)

    monkeypatch.setattr(ai, "HTTPProviders", lambda settings: MockProviders())
    if failure == "crash" and failed_provider == "deepgram":
        with pytest.raises(KeyboardInterrupt):
            worker.run_job(job_id, 0, factory, settings, storage)
    else:
        worker.run_job(job_id, 0, factory, settings, storage)
    if outcome == "success" or failed_provider == "gemini":
        with factory() as db:
            checkpointed = db.get(Job, job_id)
            assert checkpointed.state == "QUEUED" and checkpointed.checkpoint["transcript_id"]
            generation = checkpointed.generation
        if failure == "crash":
            with pytest.raises(KeyboardInterrupt):
                worker.run_job(job_id, generation, factory, settings, storage)
        else:
            worker.run_job(job_id, generation, factory, settings, storage)
    expected_calls = (
        ["deepgram", "gemini"]
        if outcome == "success" or failed_provider == "gemini"
        else ["deepgram"]
    )
    assert calls == expected_calls
    with factory() as db:
        saved = db.get(Job, job_id)
        assert saved.state == (
            "SUGGESTIONS_READY"
            if outcome == "success"
            else "RUNNING"
            if failure == "crash"
            else "FAILED"
        )
        binding_snapshot = copy.deepcopy(saved.checkpoint[acceptance.MARKER])
        if failure == "429":
            assert saved.error_code == "acceptance_provider_rejected"
    # New provider object / new worker invocation cannot resend terminal, leased,
    # cached or consumed requests. No recovery/reset is used to force a retry.
    worker.run_job(job_id, 0, factory, settings, storage)
    if failure == "crash":
        now = worker.utcnow()
        monkeypatch.setattr(worker, "utcnow", lambda: now + timedelta(seconds=1000))
        assert worker.recover(factory, storage) == 1
        with factory() as db:
            generation = db.get(Job, job_id).generation
        worker.run_job(job_id, generation, factory, settings, storage)
        with factory() as db:
            assert db.get(Job, job_id).state == "FAILED"
    assert calls == expected_calls
    with factory() as db:
        assert db.get(Job, job_id).checkpoint[acceptance.MARKER] == binding_snapshot


def test_postgres_slot_is_exclusive_between_independent_connections(guarded_processing):
    from zoclip.credits import service as money
    from zoclip.media import service

    (factory, users, settings, _), job_id = guarded_processing

    def contender():
        with factory() as db:
            money.lock_wallet(db, users["alice"])
            job = service.owned(db, Job, users["alice"], job_id, lock=True)
            try:
                acceptance.consume(
                    job,
                    settings,
                    "deepgram",
                    uuid4(),
                    job.checkpoint[acceptance.MARKER]["source_sha256"],
                )
                db.commit()
                return "dispatch"
            except ApiError as error:
                assert error.code == "acceptance_request_consumed"
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: contender(), range(2))) == ["blocked", "dispatch"]


def load_driver():
    import importlib.util

    spec = importlib.util.spec_from_file_location("acceptance_once", "scripts/acceptance_once.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("rejected", [False, True])
def test_native_driver_advances_only_successful_stages(guarded_processing, monkeypatch, rejected):
    import test_ai

    (factory, users, settings, storage), job_id = guarded_processing
    simulator = test_ai.Simulator()
    if rejected:
        simulator.dg = None

        def rejection(path):
            simulator.calls.append("deepgram")
            return {"status": 429, "body": {}}

        monkeypatch.setattr(simulator, "transcribe", rejection)
    monkeypatch.setattr(ai, "HTTPProviders", lambda settings: simulator)
    driver = load_driver()
    if rejected:
        with pytest.raises(ValueError):
            driver.advance_ai(factory, settings, users["alice"], job_id, storage)
        assert simulator.calls == ["deepgram"]
    else:
        driver.advance_ai(factory, settings, users["alice"], job_id, storage)
        assert simulator.calls == ["deepgram", "gemini"]
    with factory() as db:
        assert db.get(Job, job_id).state == ("FAILED" if rejected else "SUGGESTIONS_READY")


def test_exclusive_phase_record_survives_restart(tmp_path):
    module = load_driver()
    path = tmp_path / "entered.json"
    module.exclusive_record(path, {"job": "selected"})
    with pytest.raises(FileExistsError):
        module.exclusive_record(path, {"job": "different"})
    assert json.loads(path.read_text()) == {"job": "selected"}


@pytest.mark.parametrize("approved", [False, "true", None, True])
def test_live_approval_requires_recorded_boolean(tmp_path, monkeypatch, approved):
    module = load_driver()
    path = tmp_path / "approval.json"
    path.write_text(json.dumps({"live_processing_approved": approved}))
    monkeypatch.setattr(module, "ATTESTATION", path)
    if approved is True:
        module.require_approval()
    else:
        with pytest.raises(ValueError):
            module.require_approval()
