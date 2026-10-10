"""PostgreSQL/media security gate. Synthetic media only; never paid providers."""

import hashlib
import io
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import test_credits
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_credits import authenticate, seed

from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.credits import service as financial
from zoclip.credits.models import CreditReservation, CreditTransaction, Wallet
from zoclip.credits.schemas import QuoteInput
from zoclip.media import importer, worker
from zoclip.media import service as s
from zoclip.media.cleanup import cleanup
from zoclip.media.models import (
    Job,
    JobEvent,
    Outbox,
    SourceVideo,
    StorageObject,
    UploadPart,
    UploadSession,
)
from zoclip.media.probe import probe
from zoclip.media.schemas import ProcessInput, UploadInput
from zoclip.media.storage import LocalStorage

financial_database = test_credits.concurrent_db


@pytest.fixture
def media(financial_database, tmp_path, monkeypatch):
    factory, users = financial_database
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test:test@localhost/test",
        app_env="test",
        media_root=str(tmp_path),
        media_part_bytes=65536,
        media_allowed_import_hosts=["media.example.com"],
    )
    storage = LocalStorage(str(tmp_path))
    # Explicit synthetic disk capacity; separate tests verify the failure boundary.
    monkeypatch.setattr(storage, "free_bytes", lambda: 1024**4)
    return factory, users, settings, storage


@pytest.fixture(scope="session")
def video_bytes():
    path = Path("tests/fixtures/source.mp4")
    assert path.is_file(), "Generate the documented synthetic fixture before the gate"
    return path.read_bytes()


def upload_all(media, content, *, key="upload", owner=None, reverse=True):
    factory, users, settings, storage = media
    owner = owner or users["alice"]
    with factory() as db:
        upload = s.initiate(
            db,
            owner,
            UploadInput(
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                rights_attested=True,
            ),
            key,
            settings,
            storage,
        )
        upload_id, video_id = upload.id, upload.video_id
        db.commit()
    chunks = [
        content[start : start + settings.media_part_bytes]
        for start in range(0, len(content), settings.media_part_bytes)
    ]
    numbers = list(range(len(chunks)))
    for number in reversed(numbers) if reverse else numbers:
        data = chunks[number]
        with factory() as db:
            token, expected = s.claim_part(db, owner, upload_id, number, settings, storage)
            assert expected == len(data)
            db.commit()
        with storage.create(token) as output:
            output.write(data)
        with factory() as db:
            s.accept_part(
                db,
                owner,
                upload_id,
                number,
                token,
                len(data),
                hashlib.sha256(data).hexdigest(),
                storage,
            )
            db.commit()
    return upload_id, video_id


def ready(media, content):
    factory, users, settings, storage = media
    upload_id, video_id = upload_all(media, content)
    with factory() as db:
        job = s.finalize(db, users["alice"], upload_id, "complete", settings)
        job_id = job.id
        db.commit()
    worker.run_job(job_id, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, job_id).state == "COMPLETED"
        assert db.get(SourceVideo, video_id).state == "READY"
    return video_id, job_id


def process_job(media, video_id, key="process"):
    factory, users, settings, storage = media
    with factory() as db:
        video = db.get(SourceVideo, video_id)
        quote = financial.make_quote(
            db,
            users["alice"],
            QuoteInput(
                source_seconds=video.metadata_json["duration_seconds"],
                output_count=1,
                captions=False,
                reframe=False,
            ),
            "quote-" + key,
        )
        job = s.process(
            db,
            users["alice"],
            ProcessInput(video_id=video_id, quote_id=quote.id),
            key,
            settings,
            storage,
        )
        job_id = job.id
        db.commit()
    return job_id


def test_real_probe_and_reordered_upload_exactly_once(media, video_bytes):
    factory, users, settings, storage = media
    video_id, job_id = ready(media, video_bytes)
    worker.run_job(job_id, 0, factory, settings, storage)
    with factory() as db:
        video = db.get(SourceVideo, video_id)
        assert video.metadata_json["duration_seconds"] == 3
        assert storage.path(video.object_id).read_bytes() == video_bytes
        assert db.get(Job, job_id).attempts == 1
        assert len(list(db.scalars(select(JobEvent).where(JobEvent.job_id == job_id)))) == 3
        assert (
            db.get(
                Wallet, db.scalar(select(Wallet.id).where(Wallet.user_id == users["alice"]))
            ).reserved
            == 0
        )
    cleanup(factory, storage)
    with factory() as db:
        assert all(not storage.path(p.id).exists() for p in db.scalars(select(UploadPart)))


def test_duplicate_parts_partial_and_conflicting_checksum(media):
    content = b"abc" * 30000
    factory, users, settings, storage = media
    upload_id, video_id = upload_all(media, content)
    with factory() as db:
        token, size = s.claim_part(db, users["alice"], upload_id, 0, settings, storage)
        db.commit()
    with storage.create(token) as out:
        out.write(content[:size])
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(UploadPart))
        s.accept_part(
            db,
            users["alice"],
            upload_id,
            0,
            token,
            size,
            hashlib.sha256(content[:size]).hexdigest(),
            storage,
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(UploadPart)) == before
    storage.delete(token)
    with factory() as db:
        token, size = s.claim_part(db, users["alice"], upload_id, 0, settings, storage)
        db.commit()
    with factory() as db, pytest.raises(ApiError, match="Existing part"):
        s.accept_part(db, users["alice"], upload_id, 0, token, size, "0" * 64, storage)
    with factory() as db, pytest.raises(ApiError) as exc:
        s.delete_video(db, users["alice"], video_id)
    assert exc.value.code == "upload_busy"


def test_incomplete_upload_and_size_quota(media):
    factory, users, settings, storage = media
    data = UploadInput(size_bytes=100, sha256="a" * 64, rights_attested=True)
    with factory() as db:
        u = s.initiate(db, users["alice"], data, "one", settings, storage)
        db.commit()
        with pytest.raises(ApiError, match="All parts"):
            s.finalize(db, users["alice"], u.id, "complete", settings)
        db.rollback()
        with pytest.raises(ApiError, match="Active ingestion"):
            s.initiate(db, users["alice"], data, "two", settings, storage)
        db.rollback()
        settings.media_max_bytes = 99
        with pytest.raises(ApiError) as exc:
            s.initiate(db, users["bob"], data, "three", settings, storage)
        assert exc.value.code == "media_too_large"


def test_financial_job_hold_cancel_replay_and_unavailable_engine(media, video_bytes):
    factory, users, settings, storage = media
    video_id, _ = ready(media, video_bytes)
    job_id = process_job(media, video_id)
    worker.run_job(job_id, 0, factory, settings, storage)
    worker.run_job(job_id, 0, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.state == "WAITING_ENGINE" and job.attempts == 1
        reservation = db.get(CreditReservation, job.reservation_id)
        assert reservation.state == "HELD"
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (4, 1)
        for _ in range(10):
            assert s.cancel_job(db, users["alice"], job_id).state == "CANCELED"
        db.commit()
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (5, 0)
        assert not db.scalar(
            select(CreditTransaction.id).where(CreditTransaction.operation == "SETTLE")
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(CreditTransaction).where(CreditTransaction.operation == "RELEASE")
                    )
                )
            )
            == 1
        )


def test_post_reserve_transaction_failure_rolls_back_job_outbox_and_money(
    media, video_bytes, monkeypatch
):
    factory, users, settings, storage = media
    video_id, _ = ready(media, video_bytes)
    monkeypatch.setattr(
        s,
        "pending_gate",
        lambda *args: (_ for _ in ()).throw(RuntimeError("injected after reserve")),
    )
    with pytest.raises(RuntimeError):
        process_job(media, video_id)
    with factory() as db:
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (5, 0)
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(Outbox)) == 1


def test_insufficient_credit_and_authoritative_duration(media, video_bytes):
    factory, users, settings, storage = media
    video_id, _ = ready(media, video_bytes)
    with factory() as db:
        q = financial.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=2, output_count=1, captions=False, reframe=False),
            "bad-duration",
        )
        db.commit()
        with pytest.raises(ApiError) as exc:
            s.process(
                db,
                users["alice"],
                ProcessInput(video_id=video_id, quote_id=q.id),
                "bad",
                settings,
                storage,
            )
        assert exc.value.code == "quote_duration_mismatch"
        db.rollback()
        financial.adjust(db, users["alice"], -5, "remove", users["admin"], "Fictional test remove")
        db.commit()
    with pytest.raises(ApiError) as exc:
        process_job(media, video_id)
    assert exc.value.code == "insufficient_credits"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_simultaneous_job_requests_deduplicate_and_serialize(media, video_bytes):
    factory, users, settings, storage = media
    video_id, _ = ready(media, video_bytes)
    with factory() as db:
        quote = financial.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=3, output_count=1, captions=False, reframe=False),
            "parallel",
        )
        qid = quote.id
        db.commit()
    barrier = Barrier(10)

    def attempt(_):
        barrier.wait()
        with factory() as db:
            job = s.process(
                db,
                users["alice"],
                ProcessInput(video_id=video_id, quote_id=qid),
                "same",
                settings,
                storage,
            )
            db.commit()
            return job.id

    with ThreadPoolExecutor(max_workers=10) as executor:
        ids = list(executor.map(attempt, range(10)))
    assert len(set(ids)) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 1
        financial.reconcile(db, financial.lock_wallet(db, users["alice"]))


def test_concurrent_ingestion_and_disk_reservations(media):
    factory, users, settings, storage = media
    barrier = Barrier(2)

    def attempt(i):
        barrier.wait()
        with factory() as db:
            try:
                value = s.initiate(
                    db,
                    users["alice"],
                    UploadInput(size_bytes=10, sha256="a" * 64, rights_attested=True),
                    str(i),
                    settings,
                    storage,
                )
                db.commit()
                return value.id
            except ApiError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert results.count("ingestion_limit") == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StorageObject)) == 1


def test_full_disk_and_retained_limit_fail_closed(media, monkeypatch):
    factory, users, settings, storage = media
    data = UploadInput(size_bytes=10, sha256="a" * 64, rights_attested=True)
    monkeypatch.setattr(storage, "free_bytes", lambda: settings.media_headroom_bytes + 1)
    with factory() as db, pytest.raises(ApiError) as exc:
        s.initiate(db, users["alice"], data, "disk", settings, storage)
    assert exc.value.status == 507
    monkeypatch.setattr(storage, "free_bytes", lambda: 1024**4)
    settings.media_retained_bytes = 1
    with factory() as db, pytest.raises(ApiError) as exc:
        s.initiate(db, users["alice"], data, "disk", settings, storage)
    assert exc.value.code == "insufficient_capacity"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SourceVideo)) == 0


def test_worker_fencing_recovery_cancel_and_credit_restoration(media, video_bytes):
    factory, users, settings, storage = media
    video_id, _ = ready(media, video_bytes)
    jid = process_job(media, video_id)
    with factory() as db:
        token, owner = worker.claim(db, jid, 0)
        db.commit()
        s.cancel_job(db, owner, jid)
        db.commit()
        assert db.get(CreditReservation, db.get(Job, jid).reservation_id).state == "HELD"
        db.get(Job, jid).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert worker.recover(factory) == 1
    with factory() as db:
        assert db.get(Job, jid).state == "CANCELED"
        with pytest.raises(ApiError) as exc:
            worker.current(db, owner, jid, token)
        assert exc.value.code == "stale_worker"
        db.rollback()
        financial.reconcile(db, financial.lock_wallet(db, owner))
        assert financial.lock_wallet(db, owner).available == 5


def test_retry_recovers_ingestion_without_repeating_financial_mutations(
    media, video_bytes, monkeypatch
):
    factory, users, settings, storage = media
    uid, vid = upload_all(media, video_bytes)
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "complete", settings).id
        db.commit()
    original = worker.probe
    monkeypatch.setattr(worker, "probe", lambda *args: (_ for _ in ()).throw(OSError("temporary")))
    worker.run_job(jid, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, jid).state == "QUEUED" and db.get(Job, jid).generation == 1
    monkeypatch.setattr(worker, "probe", original)
    worker.run_job(jid, 0, factory, settings, storage)  # stale delivery
    worker.run_job(jid, 1, factory, settings, storage)
    with factory() as db:
        assert db.get(SourceVideo, vid).state == "READY"
        assert db.get(Job, jid).attempts == 2
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_malformed_media_final_failure_cleanup_and_expired_upload(media):
    factory, users, settings, storage = media
    uid, vid = upload_all(media, b"not a video")
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "complete", settings).id
        db.commit()
    worker.run_job(jid, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, jid).state == "FAILED"
        assert db.get(Job, jid).error_code == "invalid_media"
    assert cleanup(factory, storage) == 1
    uid, vid = upload_all(media, b"partial", key="expire")
    with factory() as db:
        db.get(UploadSession, uid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert cleanup(factory, storage) == 1
    with factory() as db:
        assert all(o.deleted and o.reserved_bytes == 0 for o in db.scalars(select(StorageObject)))
    assert not list(storage.root.iterdir())


def test_db_job_events_immutable(media):
    factory, users, settings, storage = media
    uid, _ = upload_all(media, b"data")
    with factory() as db:
        s.finalize(db, users["alice"], uid, "complete", settings)
        db.commit()
    for sql in (
        "DELETE FROM job_events",
        "UPDATE job_events SET state='FAILED'",
        "TRUNCATE job_events",
    ):
        with factory() as db, pytest.raises(DBAPIError):
            db.execute(text(sql))


def test_outbox_redis_failure_redelivery_and_real_rq_execution(media, video_bytes, monkeypatch):
    factory, users, settings, storage = media
    uid, vid = upload_all(media, video_bytes)
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "complete", settings).id
        db.commit()
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Disposable Redis DB 15 required for real transport integration")
    assert url.endswith("/15")
    redis = Redis.from_url(url, socket_timeout=3)
    redis.flushdb()
    enqueue = Queue.enqueue
    monkeypatch.setattr(
        Queue,
        "enqueue",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("injected Redis outage")),
    )
    with pytest.raises(ConnectionError):
        worker.dispatch(factory, redis)
    with factory() as db:
        outbox = db.scalar(select(Outbox).where(Outbox.job_id == jid))
        assert outbox.dispatched_at is None and db.get(Job, jid).state == "QUEUED"
        outbox.dispatch_until = utcnow() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(Queue, "enqueue", enqueue)
    assert worker.dispatch(factory, redis) == 1
    with factory() as db:
        # Simulate lost acknowledgment/Redis retention: duplicate delivery before claim.
        db.scalar(select(Outbox).where(Outbox.job_id == jid)).dispatched_at = utcnow() - timedelta(
            seconds=61
        )
        db.commit()
    assert worker.dispatch(factory, redis) == 1
    monkeypatch.setattr(
        worker,
        "execute",
        lambda key, generation: worker.run_job(UUID(key), generation, factory, settings, storage),
    )
    SimpleWorker([Queue("ai", connection=redis)], connection=redis).work(burst=True)
    with factory() as db:
        assert db.get(SourceVideo, vid).state == "READY"
        assert db.get(Job, jid).attempts == 1
    redis.flushdb()
    redis.close()


def test_import_worker_checkpoint_and_erasure(media, video_bytes, monkeypatch):
    from zoclip.media.schemas import ImportInput

    factory, users, settings, storage = media
    with factory() as db:
        request = ImportInput(
            url="https://media.example.com/private?token=test-placeholder",
            max_bytes=len(video_bytes),
            rights_attested=True,
        )
        first = s.import_url(db, users["alice"], request, "import", settings, storage)
        jid, vid = first.id, first.video_id
        assert s.import_url(db, users["alice"], request, "import", settings, storage).id == jid
        db.commit()

    def fake_download(url, hosts, output, max_bytes, **kwargs):
        assert max_bytes == len(video_bytes)
        output.write(video_bytes)
        return len(video_bytes)

    monkeypatch.setattr(worker, "download", fake_download)
    worker.run_job(jid, 0, factory, settings, storage)
    worker.run_job(jid, 0, factory, settings, storage)
    with factory() as db:
        assert db.get(SourceVideo, vid).state == "READY"
        assert db.get(Job, jid).payload == {} and db.get(Job, jid).attempts == 1
        assert db.get(Job, jid).checkpoint["sha256"] == hashlib.sha256(video_bytes).hexdigest()


def test_process_pending_queue_and_storage_failure_restore_atomic_hold(
    media, video_bytes, monkeypatch
):
    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    monkeypatch.setattr(storage, "free_bytes", lambda: settings.media_headroom_bytes)
    with pytest.raises(ApiError) as exc:
        process_job(media, vid)
    assert exc.value.code == "insufficient_capacity"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (5, 0)


def test_waiting_engine_timeout_restores_credits(media, video_bytes):
    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    jid = process_job(media, vid)
    worker.run_job(jid, 0, factory, settings, storage)
    with factory() as db:
        db.get(Job, jid).updated_at = utcnow() - timedelta(days=2)
        db.commit()
    cleanup(factory, storage)
    cleanup(factory, storage)
    with factory() as db:
        assert db.get(Job, jid).state == "CANCELED"
        assert financial.lock_wallet(db, users["alice"]).available == 5


def test_test_only_deterministic_engine_settlement_replay(media, video_bytes):
    """Explicit mock adapter exists ONLY here, never in application/worker code."""
    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    jid = process_job(media, vid)

    def mock_engine():
        with factory() as db:
            claimed = worker.claim(db, jid, 0)
            db.commit()
        if not claimed:
            return
        token, owner = claimed
        mock_output = b"EXPLICIT TEST MOCK - NOT A VIDEO DELIVERABLE"
        expected = hashlib.sha256(mock_output).hexdigest()
        with storage.create(token) as output:
            output.write(mock_output)
        with factory() as db:
            job = worker.current(db, owner, jid, token)
            assert storage.path(token).read_bytes() == mock_output
            financial.finish(
                db,
                owner,
                job.reservation_id,
                "mock-settle:" + str(jid),
                success=True,
                evidence=expected,
            )
            job.checkpoint = {"test_only_mock_sha256": expected}
            s.event(db, job, "COMPLETED")
            job.lease_token, job.lease_until = None, None
            db.commit()
        storage.delete(token)

    for _ in range(10):
        mock_engine()
    with factory() as db:
        assert db.get(Job, jid).state == "COMPLETED"
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "SETTLE")
            )
            == 1
        )
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (4, 0)
        financial.reconcile(db, wallet)


def test_claim_recovery_generation_and_live_worker_fence(media, video_bytes):
    factory, users, settings, storage = media
    uid, vid = upload_all(media, video_bytes)
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "complete", settings).id
        db.commit()
        token, owner = worker.claim(db, jid, 0)
        db.commit()
    assert worker.recover(factory) == 0  # A live lease cannot be recovered/released.
    with factory() as db:
        assert worker.claim(db, jid, 0) is None
        db.get(Job, jid).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert worker.recover(factory) == 1
    with factory() as db, pytest.raises(ApiError):
        worker.current(db, owner, jid, token)
    worker.run_job(jid, 0, factory, settings, storage)
    worker.run_job(jid, 1, factory, settings, storage)
    with factory() as db:
        assert db.get(SourceVideo, vid).state == "READY"
        assert db.get(Job, jid).attempts == 2


@pytest.mark.parametrize("peer", ["8.8.8.8", "127.0.0.1", "8.8.4.4"])
def test_pinned_tls_peer_and_hostname_verification(peer, monkeypatch):
    class Socket:
        def settimeout(self, value):
            pass

        def connect(self, address):
            assert address == ("8.8.8.8", 443)

        def getpeername(self):
            return peer, 443

        def close(self):
            pass

    class Context:
        def wrap_socket(self, sock, server_hostname):
            assert server_hostname == "media.example.com"
            return sock

    connection = importer.PinnedHTTPS("media.example.com", "8.8.8.8", 5)
    assert connection.tls_context.check_hostname
    assert connection.tls_context.verify_mode == __import__("ssl").CERT_REQUIRED
    connection.tls_context = Context()
    monkeypatch.setattr(importer.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(
        importer.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("Connection must not re-resolve DNS"),
    )
    if peer == "8.8.8.8":
        connection.connect()
        assert connection.sock is not None
    else:
        with pytest.raises(ApiError) as exc:
            connection.connect()
        assert exc.value.code == "unsafe_source"


def test_dns_rejects_any_private_answer_and_deadline(monkeypatch):
    import json

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, json.dumps(["8.8.8.8", "127.0.0.1"]).encode()
        ),
    )
    with pytest.raises(ApiError) as exc:
        importer.resolve("media.example.com")
    assert exc.value.code == "unsafe_source"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("DNS", 5)),
    )
    with pytest.raises(TimeoutError):
        importer.resolve("media.example.com")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.100.100.200",
        "192.168.1.1",
        "0.0.0.0",
        "::1",
        "::ffff:8.8.8.8",
        "fe80::1",
        "fc00::1",
        "224.0.0.1",
        "2001:db8::1",
    ],
)
def test_unsafe_network_addresses(address):
    assert not importer.safe_address(address)


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.com/a.mp4",
        "https://user:password@media.example.com/a",
        "https://media.example.com:444/a",
        "https://media.example.com.evil/a",
        "https://youtube.com/watch?v=x",
        "file:///etc/passwd",
        "https://media.example.com/a\r\nX: x",
        "https://media.example.com\\@evil/a",
        "https://127.0.0.1/a",
        "https://media.example.com/a#fragment",
    ],
)
def test_unsupported_url_policy(url):
    with pytest.raises(ApiError) as exc:
        importer.validate_url(url, ["media.example.com"])
    assert exc.value.code == "unsupported_source"


class FakeResponse:
    def __init__(self, data=b"", status=200, **headers):
        self.status, self.headers, self.body = status, headers, io.BytesIO(data)

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, count):
        return self.body.read(count)


class FakeConnection:
    sock = None

    def __init__(self, response):
        self.response = response

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return self.response

    def close(self):
        pass


def test_import_stream_and_redirect_revalidation(video_bytes):
    responses = [
        FakeResponse(status=302, Location="https://media.example.com/final"),
        FakeResponse(
            video_bytes, **{"Content-Type": "video/mp4", "Content-Length": str(len(video_bytes))}
        ),
    ]
    resolved, connected = [], []

    def resolver(host):
        resolved.append(host)
        return ["8.8.8.8"]

    def connect(host, ip, timeout):
        connected.append((host, ip))
        return FakeConnection(responses.pop(0))

    target = io.BytesIO()
    assert importer.download(
        "https://media.example.com/a",
        ["media.example.com"],
        target,
        len(video_bytes),
        connect=connect,
        resolver=resolver,
    ) == len(video_bytes)
    assert target.getvalue() == video_bytes and len(resolved) == len(connected) == 2


def test_dns_rebinding_and_private_redirect_blocked():
    answers = iter([["8.8.8.8"], ["127.0.0.1"]])
    response = FakeResponse(status=302, Location="/next")
    with pytest.raises(ApiError) as exc:
        importer.download(
            "https://media.example.com/a",
            ["media.example.com"],
            io.BytesIO(),
            100,
            resolver=lambda _: next(answers),
            connect=lambda *args: FakeConnection(response),
        )
    assert exc.value.code == "unsafe_source"
    response = FakeResponse(status=302, Location="https://169.254.169.254/latest")
    with pytest.raises(ApiError):
        importer.download(
            "https://media.example.com/a",
            ["media.example.com"],
            io.BytesIO(),
            100,
            resolver=lambda _: ["8.8.8.8"],
            connect=lambda *args: FakeConnection(response),
        )


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(b"x" * 101, **{"Content-Type": "video/mp4"}),
        FakeResponse(**{"Content-Type": "video/mp4", "Content-Length": "101"}),
        FakeResponse(b"html", **{"Content-Type": "text/html"}),
        FakeResponse(b"html", **{"Content-Type": "video/mp4"}),
        FakeResponse(b"", **{"Content-Type": "video/mp4", "Content-Encoding": "gzip"}),
    ],
)
def test_import_byte_content_and_magic_limits(response):
    with pytest.raises(ApiError):
        importer.download(
            "https://media.example.com/a",
            ["media.example.com"],
            io.BytesIO(),
            100,
            resolver=lambda _: ["8.8.8.8"],
            connect=lambda *args: FakeConnection(response),
        )


def test_storage_rejects_path_traversal_and_symlinks(tmp_path):
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        storage.path("../../outside")
    key = uuid4()
    with storage.create(key) as handle:
        handle.write(b"private")
    with pytest.raises(FileExistsError):
        storage.create(key)
    assert storage.path(key).parent == tmp_path
    link = tmp_path / uuid4().hex
    try:
        link.symlink_to(storage.path(key))
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; required on Linux")
        raise
    assert link.is_symlink()
    with pytest.raises(ApiError, match="Private storage unavailable"):
        storage.open(UUID(hex=link.name))
    assert storage.path(key).read_bytes() == b"private"


def test_download_waiting_on_deletion_rechecks_cached_source(media, video_bytes, monkeypatch):
    """Independent PG connections and two threads force the former stale-read race."""
    from zoclip.auth.models import User
    from zoclip.media.routes import content

    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    entered, deleted = Event(), Event()
    original = s.mutex

    def paused_mutex(db, owner, **kwargs):
        if db.info.get("download_race"):
            entered.set()
            assert deleted.wait(4), "Deletion must commit before the download acquires its lock"
        original(db, owner, **kwargs)

    monkeypatch.setattr(s, "mutex", paused_mutex)

    def download():
        with factory() as db:
            cached = db.get(SourceVideo, vid)
            assert cached.state == "READY"
            user = db.get(User, users["alice"])
            db.info["download_race"] = True
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
            with pytest.raises(ApiError) as exc:
                content(vid, request, db, user)
            return exc.value.status

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(download)
        assert entered.wait(4)
        try:
            with factory() as db:
                s.delete_video(db, users["alice"], vid)
                db.commit()
        finally:
            deleted.set()
        assert result.result(timeout=5) == 404


def test_cross_owner_upload_mutations_and_generation(app, client, video_bytes, monkeypatch):
    users = seed(app.state.session_factory)
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda _: 1024**4)
    headers = authenticate(client, app, users["alice"])
    data = {
        "size_bytes": len(video_bytes),
        "sha256": hashlib.sha256(video_bytes).hexdigest(),
        "rights_attested": True,
    }
    upload = client.post("/api/v1/uploads", json=data, headers=headers).json()
    uid, vid = upload["id"], upload["video_id"]
    bob = authenticate(client, app, users["bob"])
    part = video_bytes[: upload["part_bytes"]]
    assert (
        client.put(
            f"/api/v1/uploads/{uid}/parts/0",
            content=part,
            headers=bob
            | {
                "Content-Type": "application/octet-stream",
                "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
            },
        ).status_code
        == 404
    )
    assert client.post(f"/api/v1/uploads/{uid}/complete", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/uploads/{uid}", headers=bob).status_code == 404
    for path, body in (
        ("/api/v1/jobs", {"video_id": vid, "quote_id": str(uuid4())}),
        (f"/api/v1/videos/{vid}/generate", {"quote_id": str(uuid4())}),
    ):
        assert client.post(path, json=body, headers=bob).status_code == 404
    with app.state.session_factory() as db:
        assert db.get(UploadSession, UUID(uid)).state == "OPEN"
        assert db.get(SourceVideo, UUID(vid)).state == "UPLOADING"
        assert db.scalar(select(func.count()).select_from(UploadPart)) == 0
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_generation_alias_and_honest_job_contract(media, video_bytes, monkeypatch):
    import fakeredis
    from fastapi.testclient import TestClient

    from zoclip.main import create_app

    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    application = create_app(settings)
    application.state.session_factory = factory
    application.state.redis = fakeredis.FakeRedis()
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda _: 1024**4)
    with factory() as db:
        quote = financial.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=3, output_count=1, captions=False, reframe=False),
            "contract",
        )
        qid = quote.id
        db.commit()
    with TestClient(application, base_url="http://localhost:8000") as client:
        headers = authenticate(client, application, users["alice"])
        result = client.post(
            f"/api/v1/videos/{vid}/generate", json={"quote_id": str(qid)}, headers=headers
        )
        assert result.status_code == 202, result.text
        job = result.json()
        alias = client.post(
            "/api/v1/jobs", json={"video_id": str(vid), "quote_id": str(qid)}, headers=headers
        )
        assert alias.json()["id"] == job["id"]
        assert job["stage"] == "QUEUED" and job["progress_percent"] is None
        assert job["estimated_credits"] == 1 and job["updated_at"]
        worker.run_job(UUID(job["id"]), 0, factory, settings, storage)
        waiting = client.get(f"/api/v1/jobs/{job['id']}").json()
        assert waiting["stage"] == "WAITING_ENGINE" and waiting["progress_percent"] is None
        assert waiting["estimated_credits"] == 1
        assert client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers).status_code == 200


@pytest.mark.parametrize("boundary", ["rename", "commit", "acknowledgment"])
def test_promoted_file_commit_crash_recovery(media, video_bytes, monkeypatch, boundary):
    """Crash before rename, after rename/before commit, or after commit/lost ack."""
    factory, users, settings, storage = media
    uid, vid = upload_all(media, video_bytes)
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "crash", settings).id
        db.commit()
    session_class = factory.class_
    commit, promote = session_class.commit, storage.promote
    injected = False

    def crash_commit(db):
        nonlocal injected
        completed = any(
            isinstance(row, Job) and row.id == jid and row.state == "COMPLETED"
            for row in db.identity_map.values()
        )
        if completed and not injected and boundary != "rename":
            injected = True
            if boundary == "acknowledgment":
                commit(db)
            raise SystemExit("simulated process loss")
        commit(db)

    def crash_promote(temporary, target):
        nonlocal injected
        if target == object_id and boundary == "rename" and not injected:
            injected = True
            raise SystemExit("simulated process loss")
        promote(temporary, target)

    with factory() as db:
        object_id = db.get(SourceVideo, vid).object_id
    with monkeypatch.context() as patch:
        patch.setattr(session_class, "commit", crash_commit)
        patch.setattr(storage, "promote", crash_promote)
        with pytest.raises(SystemExit):
            worker.run_job(jid, 0, factory, settings, storage)
    assert injected
    with factory() as db:
        job = db.get(Job, jid)
        if boundary != "acknowledgment":
            assert job.state == "RUNNING" and db.get(SourceVideo, vid).state == "VALIDATING"
            job.lease_until = utcnow() - timedelta(seconds=1)
            db.commit()
        else:
            assert job.state == "COMPLETED"
    worker.recover(factory)
    worker.run_job(jid, 1 if boundary != "acknowledgment" else 0, factory, settings, storage)
    cleanup(factory, storage)
    with factory() as db:
        assert db.get(Job, jid).state == "COMPLETED"
        assert db.get(SourceVideo, vid).state == "READY"
        assert storage.path(object_id).read_bytes() == video_bytes
        assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_part_promotion_rollback_can_resume_without_false_receipt(media):
    factory, users, settings, storage = media
    with factory() as db:
        uid = s.initiate(
            db,
            users["alice"],
            UploadInput(
                size_bytes=3, sha256=hashlib.sha256(b"abc").hexdigest(), rights_attested=True
            ),
            "receipt",
            settings,
            storage,
        ).id
        db.commit()
        token, _ = s.claim_part(db, users["alice"], uid, 0, settings, storage)
        db.commit()
    with storage.create(token) as out:
        out.write(b"abc")
    with factory() as db:
        part = s.accept_part(
            db, users["alice"], uid, 0, token, 3, hashlib.sha256(b"abc").hexdigest(), storage
        )
        orphan = part.id
        db.rollback()  # Promotion happened; its receipt and accounting did not commit.
        assert db.scalar(select(func.count()).select_from(UploadPart)) == 0
        upload = db.get(UploadSession, uid)
        upload.write_until = utcnow() - timedelta(seconds=1)
        db.commit()
        token, _ = s.claim_part(db, users["alice"], uid, 0, settings, storage)
        db.commit()
    with storage.create(token) as out:
        out.write(b"abc")
    with factory() as db:
        s.accept_part(
            db, users["alice"], uid, 0, token, 3, hashlib.sha256(b"abc").hexdigest(), storage
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(UploadPart)) == 1
    os.utime(storage.path(orphan), (1, 1))
    cleanup(factory, storage)
    assert not storage.path(orphan).exists()


def test_retry_jitter_is_bounded_and_injectable(monkeypatch):
    monkeypatch.setattr(worker.random, "uniform", lambda low, high: low)
    assert worker.retry_delay(1) == 1
    assert worker.retry_delay(2) == 2
    monkeypatch.setattr(worker.random, "uniform", lambda low, high: high)
    assert worker.retry_delay(2) == 4
    assert worker.retry_delay(100) == 30


def test_concurrent_cancellation_releases_one_hold(media, video_bytes):
    factory, users, settings, storage = media
    vid, _ = ready(media, video_bytes)
    jid = process_job(media, vid)
    worker.run_job(jid, 0, factory, settings, storage)
    barrier = Barrier(10)

    def cancel(_):
        barrier.wait()
        with factory() as db:
            job = s.cancel_job(db, users["alice"], jid)
            db.commit()
            return job.state

    with ThreadPoolExecutor(max_workers=10) as executor:
        assert list(executor.map(cancel, range(10))) == ["CANCELED"] * 10
    with factory() as db:
        wallet = financial.lock_wallet(db, users["alice"])
        assert (wallet.available, wallet.reserved) == (5, 0)
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.operation == "RELEASE")
            )
            == 1
        )


def test_transient_retry_exhaustion_is_terminal_and_cleans_up(media, video_bytes, monkeypatch):
    factory, users, settings, storage = media
    uid, vid = upload_all(media, video_bytes)
    with factory() as db:
        jid = s.finalize(db, users["alice"], uid, "exhaust", settings).id
        db.commit()
    monkeypatch.setattr(
        worker, "probe", lambda *args: (_ for _ in ()).throw(OSError("unavailable"))
    )
    for generation in range(3):
        worker.run_job(jid, generation, factory, settings, storage)
    worker.run_job(jid, 2, factory, settings, storage)
    with factory() as db:
        job = db.get(Job, jid)
        assert job.state == "FAILED" and job.attempts == 3
        assert db.get(SourceVideo, vid).state == "FAILED"
    assert cleanup(factory, storage) == 1


def test_populated_phase3_downgrade_refuses_to_erase_history(media, video_bytes):
    from alembic.config import Config

    from alembic import command

    factory, users, settings, storage = media
    _, jid = ready(media, video_bytes)
    config = Config("alembic.ini")
    with factory().bind.connect() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Refusing to erase populated job history"):
            command.downgrade(config, "dd9634e4866b")
    with factory() as db:
        assert db.get(Job, jid).state == "COMPLETED"
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "7e3fcb0834e3"


def test_cleanup_deleted_history_does_not_starve_new_assets(media):
    from zoclip.media.models import Project

    factory, users, settings, storage = media
    with factory() as db:
        for index in range(101):
            project = Project(user_id=users["alice"])
            obj = StorageObject(
                user_id=users["alice"], reserved_bytes=0, materialized_bytes=0, deleted=index < 100
            )
            db.add_all([project, obj])
            db.flush()
            db.add(
                SourceVideo(
                    user_id=users["alice"],
                    project_id=project.id,
                    object_id=obj.id,
                    state="DELETED",
                    expires_at=utcnow() - timedelta(days=1),
                )
            )
        db.commit()
    assert cleanup(factory, storage) == 1
    assert cleanup(factory, storage) == 0
    with factory() as db:
        assert not db.scalar(select(StorageObject.id).where(StorageObject.deleted.is_(False)))


def test_orphan_sweep_respects_writer_grace_and_private_keys(media):
    import time

    factory, users, settings, storage = media
    old, recent = uuid4(), uuid4()
    for key in (old, recent):
        with storage.create(key) as output:
            output.write(b"private orphan fixture")
    os.utime(storage.path(old), (time.time() - 4000, time.time() - 4000))
    other = storage.root / "operator-file"
    other.write_bytes(b"not a generated storage key")
    cleanup(factory, storage)
    assert not storage.path(old).exists()
    assert storage.path(recent).exists() and other.exists()


def test_probe_duration_and_timeout_validation(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"\0\0\0\x18ftypisom" + b"x" * 20)
    payload = {
        "format": {"duration": "7200.001"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 320,
                "height": 240,
                "nb_read_packets": "1",
            },
            {"codec_type": "audio", "codec_name": "aac", "nb_read_packets": "1"},
        ],
    }

    def fake(command, **kwargs):
        import json

        assert command[0] and "-protocol_whitelist" in command and kwargs["shell"] is False
        kwargs["stdout"].write(json.dumps(payload).encode())

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(ApiError) as exc:
        probe(path)
    assert exc.value.code == "duration_exceeded"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("probe", 25)),
    )
    with pytest.raises(ApiError) as exc:
        probe(path)
    assert exc.value.code == "invalid_media"


def test_api_stream_integrity_idor_csrf_and_private_content(app, client, video_bytes, monkeypatch):
    users = seed(app.state.session_factory)
    settings = app.state.settings
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda _: 1024**4)
    headers = authenticate(client, app, users["alice"])
    data = {
        "size_bytes": len(video_bytes),
        "sha256": hashlib.sha256(video_bytes).hexdigest(),
        "rights_attested": True,
    }
    result = client.post("/api/v1/uploads", json=data, headers=headers)
    assert result.status_code == 201, result.text
    upload = result.json()
    assert client.post("/api/v1/uploads", json=data, headers=headers).json()["id"] == upload["id"]
    assert client.post("/api/v1/uploads", json=data).status_code == 403
    endpoint = f"/api/v1/uploads/{upload['id']}/parts/0"
    part = video_bytes[: upload["part_bytes"]]
    part_headers = headers | {
        "Content-Type": "application/octet-stream",
        "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
    }
    assert client.put(endpoint, content=part + b"extra", headers=part_headers).status_code == 413
    assert (
        client.put(
            endpoint, content=part, headers=part_headers | {"X-Content-SHA256": "0" * 64}
        ).status_code
        == 422
    )
    for number, start in enumerate(range(0, len(video_bytes), upload["part_bytes"])):
        part = video_bytes[start : start + upload["part_bytes"]]
        h = part_headers | {"X-Content-SHA256": hashlib.sha256(part).hexdigest()}
        target = f"/api/v1/uploads/{upload['id']}/parts/{number}"
        assert client.put(target, content=part, headers=h).status_code == 200
        assert client.put(target, content=part, headers=h).status_code == 200
    complete = client.post(
        f"/api/v1/uploads/{upload['id']}/complete", headers=headers | {"Idempotency-Key": "finish"}
    )
    assert complete.status_code == 202, complete.text
    jid, vid = complete.json()["id"], upload["video_id"]
    worker.run_job(
        UUID(jid), 0, app.state.session_factory, settings, LocalStorage(settings.media_root)
    )
    assert client.get(f"/api/v1/videos/{vid}/content").content == video_bytes
    assert client.get(f"/api/v1/jobs/{jid}").json()["state"] == "COMPLETED"
    assert "payload" not in client.get(f"/api/v1/jobs/{jid}").json()
    bob = authenticate(client, app, users["bob"])
    for path in (
        f"/uploads/{upload['id']}",
        f"/videos/{vid}",
        f"/videos/{vid}/content",
        f"/jobs/{jid}",
        f"/jobs/{jid}/events",
    ):
        assert client.get("/api/v1" + path).status_code == 404
    assert client.post(f"/api/v1/jobs/{jid}/cancel", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/videos/{vid}", headers=bob).status_code == 404
    assert client.get("/api/v1/videos").json() == []
    assert client.get("/api/v1/jobs").json() == []
    assert (
        client.post(
            "/api/v1/videos/import-url",
            json={
                "url": "https://youtube.com/watch?v=x",
                "max_bytes": 100,
                "rights_attested": True,
            },
            headers=bob,
        ).json()["code"]
        == "unsupported_source"
    )
