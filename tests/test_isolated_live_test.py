"""Real PostgreSQL locks/durability; all HTTP is MockTransport, never paid."""

import hashlib
import os
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import test_ai
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from zoclip.ai.live_test_models import LiveTest, LiveTestCall
from zoclip.ai.providers import ProviderFailure, gemini_body
from zoclip.auth.models import User
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as money
from zoclip.credits.models import SystemLimits, Wallet
from zoclip.media.models import Project, SourceVideo, StorageObject
from zoclip.media.storage import LocalStorage
from zoclip.ops import isolated_live_test as live


@pytest.fixture
def isolated(migrated_database, tmp_path, monkeypatch):
    # Each case uses its own schema; no mutation of existing/live/test data.
    from alembic.config import Config

    def blocked_http(*args, **kwargs):
        pytest.fail("Real HTTP is forbidden in offline cap tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_http)

    from alembic import command

    schema = "live_cap_" + uuid4().hex
    root = create_engine(migrated_database)
    with root.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
        db.execute(
            text("""DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='zoclip_runtime') THEN
            CREATE ROLE zoclip_runtime NOLOGIN;
          END IF;
        END $$""")
        )
        db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO zoclip_runtime'))
        db.execute(
            text(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zoclip_runtime"
            )
        )
    engine = create_engine(
        migrated_database,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC"},
    )
    with engine.begin() as db:
        config = Config("alembic.ini")
        config.attributes["connection"] = db
        command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated_database,
        media_root=str(tmp_path / "media"),
        deepgram_model="nova-3",
        deepgram_version="2025-07-31.0",
        gemini_model="gemini-3.1-flash-lite",
        deepgram_api_key="offline-deepgram-credential-0000000",
        gemini_api_key="offline-gemini-credential-000000000",
        ai_max_chunks=1,
        ai_chunk_bytes=16000,
        ai_max_candidates=1,
        ai_max_output_tokens=2048,
        ai_min_clip_seconds=2,
        ai_max_clip_seconds=26,
        render_deadline_seconds=60,
        render_max_bytes=16 * 1024**2,
    )
    storage = LocalStorage(settings.media_root)
    video_id, object_id = uuid4(), uuid4()
    data = Path("tests/fixtures/source.mp4").read_bytes()
    with storage.create(object_id) as stream:
        stream.write(data)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(live, "VIDEO_ID", video_id)
    monkeypatch.setattr(live, "SOURCE_SHA256", digest)
    monkeypatch.setattr(live, "SOURCE_BYTES", len(data))
    # Small real 2.5s fixture, synthetic 26s metadata only for guard unit cases.
    monkeypatch.setattr(live, "probe", lambda *a: {"duration_ms": 26000})
    with factory() as db:
        admin = User(email="operator@example.com", role="admin", verified=True)
        db.add(admin)
        db.flush()
        project = Project(user_id=admin.id)
        obj = StorageObject(
            id=object_id, user_id=admin.id, reserved_bytes=len(data), materialized_bytes=len(data)
        )
        db.add_all([project, obj, Wallet(user_id=admin.id)])
        db.flush()
        db.add(
            SourceVideo(
                id=video_id,
                user_id=admin.id,
                object_id=object_id,
                project_id=project.id,
                state="READY",
                metadata_json={"sha256": digest, "duration_ms": 26000, "duration_seconds": 26},
                expires_at=utcnow() + timedelta(days=7),
            )
        )
        db.commit()
        row = live.prepare(db, settings, storage, admin.id)
        job_id, actor = row.job_id, admin.id
        db.commit()
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 26 * 16000)
    yield factory, settings, storage, job_id, actor, audio, schema
    engine.dispose()
    root.dispose()


def approval(factory, settings, actor):
    with factory() as db:
        row = db.get(LiveTest, 1)
        evidence = {
            "explicit_owner_authorization": True,
            "job_id": str(row.job_id),
            "video_id": str(row.video_id),
            "source_sha256": row.source_sha256,
            "max_usd": "0.10",
            "credential_hashes": live.credential_hashes(settings),
            "credentials_account_verified": True,
            "applicable_rates_verified": row.policy["rates"],
            "source_consent_verified": True,
            "policy_hash": money.fingerprint(row.policy),
            "verification_reference": "FICTIONAL-OFFLINE-TEST-EVIDENCE",
        }
        live.approve(db, settings, actor, evidence)
        db.commit()


def dispatch(fixture, provider="deepgram", handler=None):
    factory, settings, storage, job, _, audio, _ = fixture

    def response(request):
        if handler:
            return handler(request)
        payload = test_ai.dg_payload() if provider == "deepgram" else test_ai.gemini_payload()
        return httpx.Response(200, json=payload)

    return live.provider_call(
        factory,
        settings,
        storage,
        job,
        provider,
        audio_path=audio,
        body=gemini_body("bounded transcript", settings),
        transport=httpx.MockTransport(response),
    )


def test_prepared_is_not_approval_no_credits_no_dispatch(isolated):
    factory, settings, storage, job, actor, *_ = isolated
    with factory() as db:
        assert live.prepare(db, settings, storage, actor).job_id == job
        assert db.get(LiveTest, 1).state == "PREPARED"
        assert db.scalar(select(Wallet.available)) == 0
        assert db.get(SystemLimits, 1).breaker
        assert db.scalar(text("SELECT count(*) FROM wallet_transactions")) == 0
    with pytest.raises(ApiError, match="safeguard"):
        dispatch(isolated, handler=lambda r: pytest.fail("No unapproved HTTP"))


def test_full_aggregate_all_slots_and_no_reuse(isolated):
    factory, settings, storage, job, actor, *_ = isolated
    approval(factory, settings, actor)
    dispatch(isolated)
    dispatch(isolated, "gemini")
    with factory() as db:
        slot = live.admit(db, settings, storage, job, "render")
        db.commit()
    with factory() as db:
        assert db.get(LiveTest, 1).committed_usd == Decimal("0.10")
        assert db.get(LiveTestCall, slot).state == "HELD"
    for component in ("deepgram", "gemini", "render"):
        with factory() as db, pytest.raises(ApiError):
            live.admit(db, settings, storage, job, component)


def test_two_concurrent_connections_dispatch_exactly_once(isolated):
    factory, settings, _, _, actor, *_ = isolated
    approval(factory, settings, actor)
    calls = []

    def contender(_):
        try:
            dispatch(
                isolated,
                handler=lambda r: (
                    calls.append(r.url.host) or httpx.Response(200, json=test_ai.dg_payload())
                ),
            )
            return "sent"
        except ApiError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(contender, range(2))) == ["blocked", "sent"]
    assert calls == ["api.deepgram.com"]


@pytest.mark.parametrize("outcome", ["timeout", "429", "500", "malformed", "overrun"])
@pytest.mark.parametrize("provider", ["deepgram", "gemini"])
def test_failure_stops_all_further_calls_retains_spend(isolated, outcome, provider):
    factory, settings, _, _, actor, *_ = isolated
    approval(factory, settings, actor)
    if provider == "gemini":
        dispatch(isolated)

    def fail(request):
        if outcome == "timeout":
            raise httpx.ReadTimeout("offline injected timeout")
        if outcome in {"429", "500"}:
            return httpx.Response(int(outcome), json={})
        payload = (
            {}
            if outcome == "malformed"
            else (test_ai.dg_payload() if provider == "deepgram" else test_ai.gemini_payload())
        )
        if outcome == "overrun":
            if provider == "deepgram":
                payload["metadata"]["duration"] = 61
            else:
                payload["usageMetadata"]["totalTokenCount"] = 99999
        return httpx.Response(200, json=payload)

    with pytest.raises((ApiError, ProviderFailure)):
        dispatch(isolated, provider, fail)
    with factory() as db:
        assert db.get(LiveTest, 1).state == "STOPPED"
        assert db.get(LiveTest, 1).committed_usd > 0
    with pytest.raises(ApiError):
        dispatch(isolated, provider, lambda r: pytest.fail("No paid retries"))


@pytest.mark.parametrize(
    "change",
    [
        "key",
        "config",
        "job",
        "source",
        "missing_budget",
        "expired",
        "breaker",
        "unverified_credentials",
    ],
)
def test_fail_closed_before_http(isolated, change):
    factory, settings, storage, job, actor, audio, _ = isolated
    approval(factory, settings, actor)
    if change == "key":
        settings = settings.model_copy(update={"gemini_api_key": settings.deepgram_api_key})
    elif change == "config":
        settings = settings.model_copy(update={"ai_max_chunks": 2})
    elif change == "job":
        job = uuid4()
    elif change == "source":
        with factory() as db:
            video = db.get(SourceVideo, db.get(LiveTest, 1).video_id)
            storage.path(video.object_id).write_bytes(b"changed")
    elif change == "missing_budget":
        with factory() as db:
            db.execute(text("ALTER TABLE isolated_live_test DISABLE TRIGGER isolated_test_guard"))
            db.execute(text("UPDATE isolated_live_test SET committed_usd=0.09"))
            db.commit()
    elif change == "expired":
        # Time advances, approval is immutable.
        from unittest.mock import patch

        with patch.object(live, "utcnow", lambda: utcnow() + timedelta(hours=2)):
            with factory() as db, pytest.raises(ApiError):
                live.admit(db, settings, storage, job, "deepgram")
        return
    elif change == "breaker":
        with factory() as db:
            db.get(SystemLimits, 1).breaker = False
            db.commit()
    else:
        settings = settings.model_copy(update={"gemini_api_key": type(settings.gemini_api_key)("")})
    with pytest.raises(ApiError):
        live.provider_call(
            factory,
            settings,
            storage,
            job,
            "deepgram",
            audio_path=audio,
            transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP")),
        )


def test_unknown_admission_survives_new_process_and_connections(isolated):
    factory, settings, storage, job, actor, _, schema = isolated
    approval(factory, settings, actor)
    # A distinct process commits admission and dies before any network side effect.
    code = """import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from zoclip.ai.live_test_models import LiveTestCall
e=create_engine(os.environ['TEST_DATABASE_URL'],
 connect_args={'options':'-c search_path='+os.environ['LIVE_SCHEMA']})
with sessionmaker(e)() as db:
 db.add(LiveTestCall(test_id=1,component='deepgram',ceiling_usd='0.0043'))
 db.commit()
os._exit(17)
"""
    env = dict(os.environ, LIVE_SCHEMA=schema)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True)
    assert result.returncode == 17
    with factory() as db:
        assert db.get(LiveTest, 1).committed_usd == Decimal("0.0043")
        assert db.scalar(select(LiveTestCall.state)) == "HELD"
    for component in ("deepgram", "gemini", "render"):
        with factory() as db, pytest.raises(ApiError):
            live.admit(db, settings, storage, job, component)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE isolated_live_test SET cap_usd=1",
        "UPDATE isolated_live_test SET video_id=gen_random_uuid()",
        "UPDATE isolated_live_test SET policy='{}'",
        "DELETE FROM isolated_live_test",
        "TRUNCATE isolated_live_test CASCADE",
        "UPDATE isolated_live_test_calls SET ceiling_usd=0.001",
        "DELETE FROM isolated_live_test_calls",
        "TRUNCATE isolated_live_test_calls",
        "INSERT INTO isolated_live_test_calls "
        "(id,created_at,updated_at,test_id,component,ceiling_usd,state)"
        " VALUES(gen_random_uuid(),now(),now(),1,'gemini',0.1,'HELD')",
    ],
)
def test_database_independently_rejects_reset_and_overspend(isolated, sql):
    factory, settings, _, _, actor, *_ = isolated
    approval(factory, settings, actor)
    dispatch(isolated)
    with factory() as db, pytest.raises(DBAPIError):
        db.execute(text(sql))
        db.commit()


def test_input_and_output_bounds_before_dispatch(isolated):
    factory, settings, storage, job, actor, *_ = isolated
    approval(factory, settings, actor)
    dispatch(isolated)
    for body in (
        gemini_body("x" * 36000, settings),
        {**gemini_body("x", settings), "tools": [{"google_search": {}}]},
    ):
        with pytest.raises(ApiError):
            live.provider_call(
                factory,
                settings,
                storage,
                job,
                "gemini",
                body=body,
                transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP")),
            )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LiveTestCall)) == 1


def test_missing_credential_evidence_cannot_approve(isolated):
    factory, settings, _, _, actor, *_ = isolated
    with factory() as db, pytest.raises(ApiError):
        live.approve(db, settings, actor, {"explicit_owner_authorization": True})


def test_non_durable_session_fails_closed(isolated):
    factory, settings, storage, job, actor, *_ = isolated
    approval(factory, settings, actor)
    with factory() as db:
        db.execute(text("SET LOCAL synchronous_commit = off"))
        with pytest.raises(ApiError) as error:
            live.admit(db, settings, storage, job, "deepgram")
        assert error.value.code == "live_test_database_not_durable"


def test_public_runtime_cannot_access_or_reset_operator_entitlement(isolated):
    factory, *_ = isolated
    with factory() as db:
        assert (
            db.scalar(
                text(
                    "SELECT has_table_privilege('zoclip_runtime',"
                    "'isolated_live_test','SELECT,INSERT,UPDATE,DELETE')"
                )
            )
            is False
        )
        assert (
            db.scalar(
                text(
                    "SELECT has_table_privilege('zoclip_runtime',"
                    "'isolated_live_test_calls','SELECT,INSERT,UPDATE,DELETE')"
                )
            )
            is False
        )
        db.execute(text("SET LOCAL ROLE zoclip_runtime"))
        with pytest.raises(DBAPIError):
            db.execute(text("SELECT * FROM isolated_live_test"))


@pytest.mark.parametrize("fail_render", [False, True])
def test_pipeline_one_private_clip_no_render_retry(isolated, monkeypatch, fail_render):
    from zoclip.ai.providers import HTTPProviders
    from zoclip.media import service as media
    from zoclip.rendering import engine

    factory, settings, storage, job, actor, *_ = isolated
    approval(factory, settings, actor)
    calls = []

    def response(request):
        provider = "deepgram" if request.url.host == "api.deepgram.com" else "gemini"
        calls.append(provider)
        payload = test_ai.dg_payload() if provider == "deepgram" else test_ai.gemini_payload()
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        live,
        "HTTPProviders",
        lambda s, transport=None: HTTPProviders(s, transport=httpx.MockTransport(response)),
    )
    # Capacity is outside this financial unit case, and has independent media tests.
    monkeypatch.setattr(media, "capacity", lambda *args: None)
    if fail_render:
        monkeypatch.setattr(engine, "render", lambda *args: (_ for _ in ()).throw(TimeoutError()))
        with pytest.raises(TimeoutError):
            live.execute(factory, settings, storage, job)
    else:
        result = live.execute(factory, settings, storage, job)
        assert storage.path(UUID(result["object_id"])).is_file()
        assert result["metadata"]["width"] == 720
        assert result["metadata"]["height"] == 1280
    assert calls == ["deepgram", "gemini"]
    with pytest.raises(ApiError):
        live.execute(factory, settings, storage, job)
    assert calls == ["deepgram", "gemini"]
    with factory() as db:
        assert db.get(LiveTest, 1).committed_usd == Decimal("0.10")
        assert db.scalar(select(func.count()).select_from(LiveTestCall)) == 3
        assert db.scalar(select(Wallet.available)) == 0
        assert db.scalar(text("SELECT count(*) FROM jobs WHERE kind='PROCESS'")) == 0
