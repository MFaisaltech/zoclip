"""Manual payment verification, actual PostgreSQL races and per-deliverable accounting."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import test_ai
import test_credits
from pydantic import ValidationError
from sqlalchemy import func, select

from zoclip.auth.models import AuditLog
from zoclip.billing import manual
from zoclip.billing.dashboard import overview
from zoclip.billing.models import BillingOrder, BillingRefund
from zoclip.billing.schemas import ManualPaymentInput, ManualRefundInput
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.credits import service
from zoclip.credits.models import CreditTransaction, Entitlement, SystemLimits
from zoclip.credits.schemas import ConsumptionRules, QuoteInput
from zoclip.ops.catalog import install

financial_database = test_credits.concurrent_db
media = test_ai.media
video_bytes = test_ai.video_bytes
CATALOG = json.loads(Path("deploy/staging-catalog.json").read_text())


@pytest.fixture
def purchases(financial_database):
    factory, users = financial_database
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://offline@unused/unused_test",
        app_env="test",
        manual_payments_enabled=True,
    )
    staged = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://offline:unused-secret@db/unused_test",
        app_env="production",
        private_staging=True,
        staging_site_domain="example.com",
        public_app_url="https://app.example.com",
        api_public_url="https://api.example.com",
        allowed_hosts=["api.example.com"],
    )
    with factory() as db:
        db.get(SystemLimits, 1).breaker = True
        before = db.scalar(select(func.count()).select_from(CreditTransaction))
        rows = install(db, staged, users["admin"], CATALOG)
        assert install(db, staged, users["admin"], CATALOG) == rows
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == before
        assert not list(db.scalars(select(Entitlement)))
        from uuid import UUID

        users["manual_prices"] = {row["slug"]: UUID(row["price_version_id"]) for row in rows}
        db.get(SystemLimits, 1).breaker = False  # Existing fictional test-only expense policy.
        db.commit()
    return factory, users, settings


def input_for(users, slug="creator", reference="BANK-RECEIPT-123456"):
    return ManualPaymentInput(
        price_version_id=users["manual_prices"][slug],
        amount_paisa=100000 if slug == "creator" else 200000,
        customer_name="Alice Example",
        payment_reference=reference,
        independently_verified=True,
        reason="Independently checked fictional bank statement",
    )


@pytest.mark.parametrize("slug,credits", [("creator", 10000), ("pro", 21000)])
def test_verified_activation_is_atomic_and_idempotent(purchases, slug, credits):
    factory, users, settings = purchases
    data = input_for(users, slug)
    with factory() as db:
        row = manual.activate(db, settings, users["admin"], users["alice"], data, "activate")
        order = row.id
        assert (
            manual.activate(db, settings, users["admin"], users["alice"], data, "activate").id
            == order
        )
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], credits + 5, 0)
        assert db.get(BillingOrder, order).state == "PAID"
        assert db.get(BillingOrder, order).valid_days == 30
        assert db.get(BillingOrder, order).customer_name == "Alice Example"
        assert len(list(db.scalars(select(Entitlement)))) == 1
        entitlement = db.scalar(select(Entitlement))
        assert entitlement is not None and entitlement.ends_at is not None
        assert (entitlement.ends_at - entitlement.starts_at).days == 30
        assert db.scalar(
            select(AuditLog.id).where(AuditLog.action == "billing.manual_payment_verified")
        )
        assert (
            service.calculate(
                QuoteInput(source_seconds=7200, output_count=3),
                ConsumptionRules.model_validate(service.active_price(db, users["alice"]).rules),
            )
            == 150
        )


def test_duplicate_reference_across_keys_accounts_and_concurrent_deliveries(purchases):
    factory, users, settings = purchases
    data = input_for(users)
    barrier = Barrier(2)

    def run(owner, key):
        with factory() as db:
            barrier.wait()
            try:
                row = manual.activate(db, settings, users["admin"], owner, data, key)
                db.commit()
                return str(row.id)
            except ApiError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda case: run(*case), [(users["alice"], "first"), (users["bob"], "second")])
        )
    assert results.count("payment_already_used") == 1
    with factory() as db:
        assert len(list(db.scalars(select(BillingOrder)))) == 1
        assert len(list(db.scalars(select(Entitlement)))) == 1
    with factory() as db:
        with pytest.raises(ApiError, match="already been recorded"):
            manual.activate(
                db,
                settings,
                users["admin"],
                users["alice"],
                input_for(users, reference="bank receipt 123456"),
                "third",
            )


@pytest.mark.parametrize("mode", ["customer", "disabled", "amount", "stale"])
def test_authorization_amount_and_version_checks_grant_nothing(purchases, mode):
    factory, users, settings = purchases
    data = input_for(users)
    actor = users["alice"] if mode == "customer" else users["admin"]
    if mode == "disabled":
        settings = settings.model_copy(update={"manual_payments_enabled": False})
    if mode == "amount":
        data = data.model_copy(update={"amount_paisa": 1})
    if mode == "stale":
        data = data.model_copy(update={"price_version_id": users["prices"]["creator"]})
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(CreditTransaction))
        with pytest.raises(ApiError):
            manual.activate(db, settings, actor, users["alice"], data, "blocked")
        db.rollback()
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == before
        assert not list(db.scalars(select(BillingOrder)))


def test_refund_preserves_holds_nonnegative_balances_and_replay(purchases):
    factory, users, settings = purchases
    data = input_for(users)
    with factory() as db:
        row = manual.activate(db, settings, users["admin"], users["alice"], data, "purchase")
        order = row.id
        quote = service.make_quote(
            db, users["alice"], QuoteInput(source_seconds=60, output_count=1), "quote"
        )
        held = service.reserve(db, users["alice"], quote.id, uuid4(), "reserve")
        reservation = held.id
        db.commit()
    refund = ManualRefundInput(
        payment_reference="REFUND123456",
        independently_verified=True,
        reason="Fictional external full refund independently verified",
    )
    with factory() as db:
        manual.refund(db, settings, users["admin"], order, refund, "refund")
        manual.refund(db, settings, users["admin"], order, refund, "refund")
        db.commit()
    with factory() as db:
        wallet = service.lock_wallet(db, users["alice"], active_required=False)
        assert (wallet.available, wallet.reserved) == (0, 50)
        assert db.scalar(select(BillingRefund)).unrecovered_credits == 45
        assert (
            manual.activate(db, settings, users["admin"], users["alice"], data, "purchase").state
            == "REFUNDED"
        )
        service.finish(
            db, users["alice"], reservation, "cancel", success=False, evidence="failed-job"
        )
        db.commit()
    with factory() as db:
        wallet = service.lock_wallet(db, users["alice"], active_required=False)
        assert (wallet.available, wallet.reserved) == (50, 0)


def test_partial_delivery_charges_only_completed_clips_and_refunds_once(purchases):
    factory, users, settings = purchases
    with factory() as db:
        manual.activate(db, settings, users["admin"], users["alice"], input_for(users), "paid")
        quote = service.make_quote(
            db, users["alice"], QuoteInput(source_seconds=7200, output_count=3), "three"
        )
        hold = service.reserve(db, users["alice"], quote.id, uuid4(), "hold")
        reservation = hold.id
        transaction = service.finish(
            db,
            users["alice"],
            reservation,
            "settle",
            success=True,
            evidence="one-verified-output",
            settled_credits=50,
        )
        charge = transaction.id
        service.finish(
            db,
            users["alice"],
            reservation,
            "settle",
            success=True,
            evidence="one-verified-output",
            settled_credits=50,
        )
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 9955, 0)
        summary = overview(db, users["alice"])
        assert (summary.settled_credits, summary.released_credits, summary.daily_used_credits) == (
            50,
            100,
            50,
        )
        service.refund(
            db,
            users["alice"],
            charge,
            50,
            "refund-charge",
            users["admin"],
            "Verified full charge refund",
        )
        service.refund(
            db,
            users["alice"],
            charge,
            50,
            "refund-charge",
            users["admin"],
            "Verified full charge refund",
        )
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 10005, 0)
        with pytest.raises(ApiError):
            service.refund(
                db,
                users["alice"],
                charge,
                1,
                "over-refund",
                users["admin"],
                "Duplicate refund must be blocked",
            )


def test_manual_confirmation_and_paid_provider_configuration_fail_closed():
    with pytest.raises(ValidationError):
        ManualPaymentInput(
            price_version_id=uuid4(),
            amount_paisa=100000,
            customer_name="Fake Buyer",
            payment_reference="FAKE123456",
            independently_verified=False,
            reason="Unverified screenshot",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://offline/unused_test",
            manual_payments_enabled=True,
            analysis_provider="gemini",
            gemini_api_key="not-live",
        )


def test_maximum_length_request_key_stays_idempotent(purchases):
    factory, users, settings = purchases
    key = "k" * 128
    with factory() as db:
        row = manual.activate(db, settings, users["admin"], users["alice"], input_for(users), key)
        assert len(row.operation_key) <= 128
        assert (
            manual.activate(db, settings, users["admin"], users["alice"], input_for(users), key).id
            == row.id
        )
        db.commit()
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 10005, 0)


def test_admin_routes_require_auth_role_csrf_and_exact_verified_payment(purchases):
    import fakeredis
    from fastapi.testclient import TestClient

    from zoclip.auth.models import User
    from zoclip.main import create_app

    factory, users, settings = purchases
    app = create_app(settings.model_copy(update={"cookie_secure": False}))
    app.state.session_factory = factory
    app.state.redis = fakeredis.FakeRedis()
    with factory() as db:
        email = db.get(User, users["alice"]).email
    endpoint = f"/api/v1/admin/manual-payments/users/{users['alice']}/activate"
    body = input_for(users).model_dump(mode="json")
    with TestClient(app, base_url="http://localhost:8000") as client:
        assert (
            client.get("/api/v1/admin/manual-payments/users", params={"email": email}).status_code
            == 401
        )
        test_credits.authenticate(client, app, users["alice"])
        assert (
            client.get("/api/v1/admin/manual-payments/users", params={"email": email}).status_code
            == 403
        )
        headers = test_credits.authenticate(client, app, users["admin"])
        found = client.get("/api/v1/admin/manual-payments/users", params={"email": email})
        assert found.status_code == 200 and found.json()[0]["id"] == str(users["alice"])
        assert client.post(endpoint, json=body).status_code == 403
        assert (
            client.post(endpoint, headers=headers, json=body | {"credits": 999999}).status_code
            == 422
        )
        result = client.post(endpoint, headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["order"]["sandbox"] is False
        assert (
            client.post(endpoint, headers=headers, json=body).json()["order"]["id"]
            == result.json()["order"]["id"]
        )
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 10005, 0)


def test_manual_grant_failure_rolls_back_all_payment_records(purchases, monkeypatch):
    from zoclip.billing import service as billing

    factory, users, settings = purchases
    original = billing.grant_payment

    def crash(db, order, wallet):
        original(db, order, wallet)
        raise RuntimeError("Simulated transaction failure")

    monkeypatch.setattr(billing, "grant_payment", crash)
    with factory() as db:
        with pytest.raises(RuntimeError):
            manual.activate(db, settings, users["admin"], users["alice"], input_for(users), "crash")
        db.rollback()
        assert not list(db.scalars(select(BillingOrder)))
        assert not list(db.scalars(select(Entitlement)))
        test_credits.assert_wallet(db, users["alice"], 5, 0)


def test_local_pipeline_delivers_one_of_three_and_settles_fifty(
    purchases, media, video_bytes, monkeypatch, tmp_path
):
    import test_media

    from zoclip.ai import worker as ai
    from zoclip.credits.schemas import PolicyInput
    from zoclip.media import service as jobs
    from zoclip.media import worker
    from zoclip.media.models import Job, SourceVideo
    from zoclip.media.schemas import ProcessInput
    from zoclip.rendering.models import RenderOutput

    factory, users, settings, storage = media
    import subprocess

    source = tmp_path / "three-seconds.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            "tests/fixtures/source.mp4",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    test_media.ready(media, source.read_bytes())
    settings = test_ai.configure(factory, users, settings)
    settings = Settings(
        _env_file=None,
        **(
            settings.model_dump()
            | {
                "transcription_provider": "whisper",
                "analysis_provider": "local",
                "deepgram_api_key": "",
                "gemini_api_key": "",
            }
        ),
    )
    simulator = test_ai.Simulator()
    monkeypatch.setattr(ai, "LocalWhisperProviders", lambda _: simulator)

    def forbidden(*args, **kwargs):
        pytest.fail("Paid provider must not execute")

    monkeypatch.setattr(ai, "HTTPProviders", forbidden)
    with factory() as db:
        manual.activate(
            db, purchases[2], users["admin"], users["alice"], input_for(users), "pipeline-payment"
        )
        service.configure_policy(
            db,
            PolicyInput(
                limits=users["ai_limits"].model_copy(
                    update={"render_cpu_seconds_per_output": 520, "storage_gb_days_per_output": 2}
                ),
                reason="Fictional local render limits",
            ),
            "render-limits",
            users["admin"],
        )
        video = db.scalar(select(SourceVideo).where(SourceVideo.state == "READY"))
        quote = service.make_quote(
            db,
            users["alice"],
            QuoteInput(source_seconds=video.metadata_json["duration_seconds"], output_count=3),
            "pipeline-quote",
        )
        job = jobs.process(
            db,
            users["alice"],
            ProcessInput(video_id=video.id, quote_id=quote.id, auto_render=True),
            "pipeline-job",
            settings,
            storage,
        )
        job_id = job.id
        db.commit()
    for _ in range(20):
        with factory() as db:
            row = db.get(Job, job_id)
            state, generation = row.state, row.generation
        if state != "QUEUED":
            break
        worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        assert db.get(Job, job_id).state == "COMPLETED", db.get(Job, job_id).error_code
        outputs = list(db.scalars(select(RenderOutput).where(RenderOutput.job_id == job_id)))
        assert len(outputs) == 1 and outputs[0].state == "COMPLETE"
        test_credits.assert_wallet(db, users["alice"], 9955, 0)
        assert overview(db, users["alice"]).released_credits == 100
    worker.run_job(job_id, generation, factory, settings, storage)
    with factory() as db:
        test_credits.assert_wallet(db, users["alice"], 9955, 0)
