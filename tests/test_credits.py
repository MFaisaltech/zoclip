"""Real PostgreSQL financial tests. All costs/rates are fictional test data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from alembic import command
from zoclip.auth.models import AuditLog, AuthSession, User
from zoclip.core.db import build_engine, utcnow
from zoclip.core.errors import ApiError
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits import service as s
from zoclip.credits.models import (
    CreditReservation,
    CreditTransaction,
    Plan,
    PlanPrice,
    ProviderUsage,
    SpendAttempt,
    SystemLimits,
    Wallet,
)
from zoclip.credits.schemas import (
    BudgetLimits,
    ConsumptionRules,
    PlanVersionInput,
    PolicyInput,
    QuoteInput,
    RateInput,
)

pytestmark = pytest.mark.integration
REASON = "Explicit fictional test allowance"
INPUT = QuoteInput(source_seconds=60, output_count=1, captions=False, reframe=False)


def seed(factory, *, balance=5):
    with factory() as db:
        admin = User(email=f"staff-{uuid4()}@example.com", verified=True, role="admin")
        alice = User(email=f"alice-{uuid4()}@example.com", verified=True)
        bob = User(email=f"bob-{uuid4()}@example.com", verified=True)
        db.add_all([admin, alice, bob])
        db.flush()
        rules = ConsumptionRules(
            credits_per_minute=1,
            credits_per_output=0,
            credits_per_edit=0,
            captions_credits=0,
            reframe_credits=0,
            max_source_seconds=7200,
            max_outputs=10,
            max_edits=5,
            max_concurrent_jobs=10,
            daily_credits=1000,
            monthly_credits=10000,
        )
        prices = {}
        for plan in db.scalars(select(Plan)):
            prices[plan.slug] = s.configure_plan(
                db,
                plan.id,
                PlanVersionInput(
                    price_paisa=0,
                    included_credits=2,
                    valid_days=30 if plan.slug in {"creator", "pro", "business"} else 0,
                    rules=rules,
                    reason=REASON,
                ),
                "test-version",
                admin.id,
            ).id
        rates = {}
        for component, unit, cost in [
            ("deepgram", "minute", "0.01"),
            ("gemini_input", "token", "0.000001"),
            ("gemini_output", "token", "0.000001"),
            ("render", "cpu_second", "0.00001"),
            ("storage", "gb_day", "0.001"),
        ]:
            rates[component] = s.configure_rate(
                db,
                RateInput(
                    component=component,
                    unit=unit,
                    unit_usd=Decimal(cost),
                    model="fictional-test",
                    max_units=1000000,
                    reason=REASON,
                ),
                "test-rate",
                admin.id,
            ).id
        limits = BudgetLimits(
            per_job_usd=Decimal("10"),
            user_daily_usd=Decimal("100"),
            user_monthly_usd=Decimal("100"),
            global_daily_usd=Decimal("100"),
            global_monthly_usd=Decimal("100"),
            max_open_reservations=100,
            rate_ids=list(rates.values()),
            input_tokens_per_second=1,
            max_output_tokens=10,
            render_cpu_seconds_per_output=1,
            storage_gb_days_per_output=1,
            max_attempts_per_job=20,
        )
        s.configure_policy(db, PolicyInput(limits=limits, reason=REASON), "test-policy", admin.id)
        for user in (alice, bob):
            if balance:
                s.adjust(db, user.id, balance, "seed", admin.id, REASON, grant=True)
        db.commit()
        return {
            "alice": alice.id,
            "bob": bob.id,
            "admin": admin.id,
            "rules": rules,
            "prices": prices,
            "rates": rates,
            "limits": limits,
        }


@pytest.fixture
def money(app):
    return seed(app.state.session_factory)


@pytest.fixture
def concurrent_db(migrated_database, monkeypatch):
    """Migrate a fresh schema; independent connections, no shared savepoints.

    Only this generated schema in the explicitly disposable _test DB is dropped.
    No mutation triggers are bypassed for test cleanup.
    """
    schema = "financial_test_" + uuid4().hex
    monkeypatch.setenv("DATABASE_URL", migrated_database)
    root = build_engine(migrated_database)
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        migrated_database,
        pool_size=12,
        max_overflow=0,
        connect_args={
            "options": f"-c search_path={schema} -c timezone=UTC "
            "-c statement_timeout=10000 -c lock_timeout=5000"
        },
        hide_parameters=True,
    )
    config = Config("alembic.ini")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        factory = sessionmaker(engine, expire_on_commit=False)
        yield factory, seed(factory)
    finally:
        engine.dispose()
        assert schema.startswith("financial_test_") and len(schema) == 47
        with root.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def quote_and_reserve(db, owner, key="one"):
    quote = s.make_quote(db, owner, INPUT, "quote-" + key)
    return s.reserve(db, owner, quote.id, uuid4(), "reserve-" + key)


def assert_wallet(db, owner, available, reserved):
    wallet = s.lock_wallet(db, owner)
    assert (wallet.available, wallet.reserved) == (available, reserved)
    s.reconcile(db, wallet)


def authenticate(client, app, owner):
    raw, csrf = uuid4().hex, uuid4().hex
    with app.state.session_factory() as db:
        db.add(
            AuthSession(
                user_id=owner,
                token_hash=digest(raw),
                csrf_hash=digest(csrf),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        db.commit()
    client.cookies.set(COOKIE_NAME, raw)
    return {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf, "Idempotency-Key": "request"}


def test_ten_duplicate_operations_reconcile(app, money):
    with app.state.session_factory() as db:
        uid, admin = money["alice"], money["admin"]
        for _ in range(10):
            s.adjust(db, uid, 5, "grant", admin, REASON, grant=True)
        q = s.make_quote(db, uid, INPUT, "quote")
        job = uuid4()
        for _ in range(10):
            assert s.make_quote(db, uid, INPUT, "quote").id == q.id
            reservation = s.reserve(db, uid, q.id, job, "reserve")
        for _ in range(10):
            settled = s.finish(db, uid, reservation.id, "settle", success=True, evidence="output-1")
        for _ in range(10):
            s.refund(db, uid, settled.id, 1, "refund", admin, REASON)
        for _ in range(10):
            s.adjust(db, uid, -1, "adjust", admin, REASON)
        assert_wallet(db, uid, 9, 0)
        assert (
            db.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.user_id == uid)
            )
            == 6
        )


def test_release_after_failure_and_retry(app, money):
    with app.state.session_factory() as db:
        reservation = quote_and_reserve(db, money["alice"])
        assert_wallet(db, money["alice"], 4, 1)
        for _ in range(10):
            s.finish(
                db, money["alice"], reservation.id, "failure", success=False, evidence="failed-1"
            )
        assert_wallet(db, money["alice"], 5, 0)
        with pytest.raises(ApiError, match="already finalized"):
            s.finish(
                db, money["alice"], reservation.id, "late-success", success=True, evidence="output"
            )


@pytest.mark.parametrize("changed", ["amount", "operation", "reason"])
def test_reused_keys_reject_different_payload(app, money, changed):
    with app.state.session_factory() as db:
        with pytest.raises(ApiError) as exc:
            s.adjust(
                db,
                money["alice"],
                5 if changed != "amount" else 6,
                "seed",
                money["admin"],
                REASON if changed != "reason" else "Different audited reason",
                grant=changed != "operation",
            )
        assert exc.value.code == "idempotency_conflict"
        assert_wallet(db, money["alice"], 5, 0)


def test_quote_and_finish_payload_conflicts(app, money):
    with app.state.session_factory() as db:
        q = s.make_quote(db, money["alice"], INPUT, "q")
        with pytest.raises(ApiError) as exc:
            s.make_quote(db, money["alice"], INPUT.model_copy(update={"source_seconds": 61}), "q")
        assert exc.value.code == "idempotency_conflict"
        row = s.reserve(db, money["alice"], q.id, uuid4(), "r")
        s.finish(db, money["alice"], row.id, "done", success=True, evidence="output")
        with pytest.raises(ApiError) as exc:
            s.finish(db, money["alice"], row.id, "done", success=False, evidence="output")
        assert exc.value.code == "idempotency_conflict"


def test_grant_reversal_cannot_consume_reserved_or_overrefund(app, money):
    with app.state.session_factory() as db:
        grant = db.scalars(
            select(CreditTransaction).where(CreditTransaction.user_id == money["alice"])
        ).one()
        row = quote_and_reserve(db, money["alice"])
        with pytest.raises(ApiError) as exc:
            s.refund(db, money["alice"], grant.id, 5, "reverse", money["admin"], REASON)
        assert exc.value.code == "insufficient_credits"
        s.finish(db, money["alice"], row.id, "release", success=False, evidence="failed")
        s.refund(db, money["alice"], grant.id, 5, "reverse", money["admin"], REASON)
        with pytest.raises(ApiError) as exc:
            s.refund(db, money["alice"], grant.id, 1, "over", money["admin"], REASON)
        assert exc.value.code == "refund_exceeds_original"
        assert_wallet(db, money["alice"], 0, 0)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
@pytest.mark.parametrize(
    "table",
    [
        "wallet_transactions",
        "credit_quotes",
        "plan_price_versions",
        "user_entitlements",
        "cost_rate_versions",
        "cost_policy_versions",
        "provider_usage",
    ],
)
def test_financial_history_is_immutable(app, money, table, operation):
    # Statement triggers reject mutation even when the target table is empty.
    sql = f"UPDATE {table} SET id = id" if operation == "UPDATE" else f"{operation} {table}"
    if operation == "DELETE":
        sql = f"DELETE FROM {table}"
    with app.state.session_factory() as db, pytest.raises(DBAPIError):
        db.execute(text(sql))


@pytest.mark.parametrize("column", ["available", "reserved"])
def test_db_nonnegative_constraints(app, money, column):
    with app.state.session_factory() as db, pytest.raises(IntegrityError):
        db.execute(update(Wallet).where(Wallet.user_id == money["alice"]).values({column: -1}))


def test_materialized_balance_tampering_fails_reconciliation(app, money):
    with app.state.session_factory() as db:
        db.execute(update(Wallet).where(Wallet.user_id == money["alice"]).values(available=100))
        with pytest.raises(ApiError) as exc:
            s.lock_wallet(db, money["alice"])
        assert exc.value.code == "accounting_mismatch"


def test_atomic_failure_rolls_back_then_retry_succeeds(app, money, monkeypatch):
    original = s.entry

    def fail_after_ledger(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated transaction failure")

    with app.state.session_factory() as db:
        qid = s.make_quote(db, money["alice"], INPUT, "q").id
        db.commit()
    job = uuid4()
    monkeypatch.setattr(s, "entry", fail_after_ledger)
    with app.state.session_factory() as db, pytest.raises(RuntimeError):
        s.reserve(db, money["alice"], qid, job, "r")
    monkeypatch.setattr(s, "entry", original)
    with app.state.session_factory() as db:
        assert_wallet(db, money["alice"], 5, 0)
        row = s.reserve(db, money["alice"], qid, job, "r")
        assert_wallet(db, money["alice"], 4, 1)
        s.finish(db, money["alice"], row.id, "failure", success=False, evidence="failed")
        assert_wallet(db, money["alice"], 5, 0)


def test_quote_math_limits_and_no_charge(app, money):
    with app.state.session_factory() as db:
        q = s.make_quote(db, money["alice"], INPUT.model_copy(update={"source_seconds": 61}), "q")
        assert q.credits == 2
        assert_wallet(db, money["alice"], 5, 0)
        for fields in ({"source_seconds": 7201}, {"output_count": 11}, {"edit_count": 6}):
            with pytest.raises(ApiError) as exc:
                s.make_quote(db, money["alice"], INPUT.model_copy(update=fields), uuid4().hex)
            assert exc.value.code == "plan_limit"
        with pytest.raises(ApiError) as exc:
            s.make_quote(db, money["alice"], INPUT, "production", production=True)
        assert exc.value.code == "price_unapproved"


def test_insufficient_credit_and_missing_budgets_fail_closed(app, money):
    with app.state.session_factory() as db:
        q = s.make_quote(db, money["alice"], INPUT.model_copy(update={"source_seconds": 360}), "q")
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], q.id, uuid4(), "r")
        assert exc.value.code == "insufficient_credits"
        db.get(SystemLimits, 1).breaker = True
        q = s.make_quote(db, money["alice"], INPUT, "q2")
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], q.id, uuid4(), "r2")
        assert exc.value.code == "spending_disabled"
        assert_wallet(db, money["alice"], 5, 0)


def test_stale_quote_and_unique_job_links(app, money):
    with app.state.session_factory() as db:
        q = s.make_quote(db, money["alice"], INPUT, "q")
        free = db.get(PlanPrice, money["prices"]["free"])
        s.configure_plan(
            db,
            free.plan_id,
            PlanVersionInput(
                price_paisa=0, included_credits=1, valid_days=0, rules=money["rules"], reason=REASON
            ),
            "new-version",
            money["admin"],
        )
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], q.id, uuid4(), "r")
        assert exc.value.code == "quote_stale"
        row = quote_and_reserve(db, money["alice"], "new")
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], row.quote_id, row.job_id, "another-key")
        assert exc.value.code == "reservation_exists"


def test_allowance_once_topups_renewal_and_credit_rollover(app, money, monkeypatch):
    with app.state.session_factory() as db:
        uid, actor = money["alice"], money["admin"]
        for _ in range(10):
            first = s.grant_entitlement(
                db, uid, money["prices"]["creator"], "access", actor, REASON
            )
        assert_wallet(db, uid, 7, 0)
        second = s.grant_entitlement(db, uid, money["prices"]["creator"], "renew", actor, REASON)
        assert second.starts_at == first.ends_at
        assert second.ends_at == first.ends_at + timedelta(days=30)
        s.grant_entitlement(db, uid, money["prices"]["topup"], "topup", actor, REASON)
        assert s.active_price(db, uid).id == money["prices"]["creator"]
        assert_wallet(db, uid, 11, 0)
        future = second.ends_at + timedelta(seconds=1)
        monkeypatch.setattr(s, "utcnow", lambda: future)
        assert s.active_price(db, uid).id == money["prices"]["free"]
        assert_wallet(db, uid, 11, 0)  # Access expiry never silently destroys credits.


def test_free_allowance_cannot_repeat(app, money):
    with app.state.session_factory() as db:
        s.grant_entitlement(
            db, money["alice"], money["prices"]["free"], "free", money["admin"], REASON
        )
        with pytest.raises(ApiError) as exc:
            s.grant_entitlement(
                db, money["alice"], money["prices"]["free"], "free2", money["admin"], REASON
            )
        assert exc.value.code == "allowance_already_granted"


def test_free_award_does_not_override_current_paid_access(app, money):
    with app.state.session_factory() as db:
        s.grant_entitlement(
            db, money["alice"], money["prices"]["creator"], "paid", money["admin"], REASON
        )
        s.grant_entitlement(
            db, money["alice"], money["prices"]["free"], "free", money["admin"], REASON
        )
        assert s.active_price(db, money["alice"]).id == money["prices"]["creator"]


def test_expense_hold_uncertainty_actual_cost_and_sunk_failure(app, money):
    with app.state.session_factory() as db:
        uid = money["alice"]
        row = quote_and_reserve(db, uid)
        attempt, fresh = s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 2, "call")
        assert fresh and attempt.estimated_usd == Decimal("0.02")
        assert not s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 2, "call")[1]
        s.record_spend(db, uid, attempt.id, units=None, outcome="unknown", evidence="timeout")
        with pytest.raises(ApiError) as exc:
            s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 2, "blind-retry")
        assert exc.value.code == "uncertain_spend"
        for _ in range(10):
            s.record_spend(
                db, uid, attempt.id, units=2, outcome="failure", evidence="provider-record"
            )
        s.finish(db, uid, row.id, "release", success=False, evidence="failed")
        usage = db.scalars(select(ProviderUsage)).one()
        assert usage.actual_usd == Decimal("0.02")
        assert_wallet(db, uid, 5, 0)
        with pytest.raises(ApiError):
            s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 1, "after-failure")


def test_expense_overrun_recorded_and_breaker_opened(app, money):
    with app.state.session_factory() as db:
        row = quote_and_reserve(db, money["alice"])
        attempt, _ = s.admit_spend(
            db, money["alice"], row.id, money["rates"]["deepgram"], 1, "call"
        )
        s.record_spend(db, money["alice"], attempt.id, units=2, outcome="success", evidence="usage")
        assert db.get(SystemLimits, 1).breaker
        assert db.scalars(select(ProviderUsage)).one().actual_usd == Decimal("0.02")
        with pytest.raises(ApiError) as exc:
            s.admit_spend(db, money["alice"], row.id, money["rates"]["deepgram"], 1, "next")
        assert exc.value.code == "spending_disabled"


@pytest.mark.parametrize(
    "field",
    ["per_job_usd", "user_daily_usd", "user_monthly_usd", "global_daily_usd", "global_monthly_usd"],
)
def test_every_budget_dimension_counts_inflight_and_actual(app, money, field):
    with app.state.session_factory() as db:
        row = quote_and_reserve(db, money["alice"])
        limits = money["limits"].model_copy(update={field: Decimal("0.02")})
        s.configure_policy(
            db, PolicyInput(limits=limits, reason=REASON), "small-budget", money["admin"]
        )
        attempt, _ = s.admit_spend(
            db, money["alice"], row.id, money["rates"]["deepgram"], 2, "call"
        )
        s.record_spend(
            db, money["alice"], attempt.id, units=2, outcome="failure", evidence="billable"
        )
        with pytest.raises(ApiError) as exc:
            s.admit_spend(db, money["alice"], row.id, money["rates"]["deepgram"], 1, "retry")
        assert exc.value.code == "budget_exceeded"


def test_unknown_exposure_survives_month_boundary(app, money, monkeypatch):
    with app.state.session_factory() as db:
        row = quote_and_reserve(db, money["alice"])
        attempt, _ = s.admit_spend(
            db, money["alice"], row.id, money["rates"]["deepgram"], 2, "call"
        )
        s.record_spend(
            db, money["alice"], attempt.id, units=None, outcome="unknown", evidence="timeout"
        )
        limits = money["limits"].model_copy(update={"global_monthly_usd": Decimal("0.02")})
        monkeypatch.setattr(s, "utcnow", lambda: utcnow() + timedelta(days=70))
        with pytest.raises(ApiError) as exc:
            s.check_budgets(db, limits, money["bob"], None, Decimal("0.01"))
        assert exc.value.code == "budget_exceeded"


def test_customer_api_is_scoped_strict_and_cannot_grant(client, app, money):
    headers = authenticate(client, app, money["alice"])
    assert client.get("/api/v1/me/credits").json()["available_credits"] == 5
    history = client.get("/api/v1/me/credit-transactions").json()
    assert len(history["items"]) == 1
    assert "actor_id" not in str(history) and "reason" not in str(history)
    assert (
        client.post(
            f"/api/v1/admin/users/{money['alice']}/credit-adjustments",
            headers=headers,
            json={"amount": 100, "reason": REASON},
        ).status_code
        == 403
    )
    for extra in ({"user_id": str(money["bob"])}, {"credits": 0}, {"price_paisa": 0}):
        assert (
            client.post(
                "/api/v1/jobs/quote", headers=headers, json=INPUT.model_dump() | extra
            ).status_code
            == 422
        )
    for _ in range(10):
        response = client.post("/api/v1/jobs/quote", headers=headers, json=INPUT.model_dump())
        assert response.status_code == 200, response.text
    qid = UUID(response.json()["id"])
    assert client.get("/api/v1/me/credits").json()["available_credits"] == 5
    assert client.post("/api/v1/jobs/quote", json=INPUT.model_dump()).status_code == 403
    with app.state.session_factory() as db:
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["bob"], qid, uuid4(), "foreign")
        assert exc.value.code == "not_found"
        grant = db.scalar(
            select(CreditTransaction).where(CreditTransaction.user_id == money["alice"])
        )
        with pytest.raises(ApiError):
            s.refund(db, money["bob"], grant.id, 1, "foreign", money["admin"], REASON)


def test_staff_api_audited_idempotent_and_pagination(client, app, money):
    headers = authenticate(client, app, money["admin"])
    url = f"/api/v1/admin/users/{money['alice']}/credit-adjustments"
    for _ in range(10):
        result = client.post(url, headers=headers, json={"amount": 3, "reason": REASON})
        assert result.status_code == 200, result.text
    assert (
        client.post(url, headers=headers, json={"amount": 4, "reason": REASON}).status_code == 409
    )
    assert client.post(url, headers=headers, json={"amount": 4, "reason": ""}).status_code == 422
    assert client.get("/api/v1/admin/usage-costs").status_code == 200
    assert client.get("/api/v1/admin/limits").status_code == 200
    headers = authenticate(client, app, money["alice"])
    page = client.get("/api/v1/me/credit-transactions?limit=1").json()
    next_page = client.get(
        f"/api/v1/me/credit-transactions?limit=1&cursor={page['next_cursor']}"
    ).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert next_page["next_cursor"] is None
    assert client.get("/api/v1/admin/usage-costs").status_code == 403
    with app.state.session_factory() as db:
        assert_wallet(db, money["alice"], 8, 0)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "credits.admin_adjust")
            )
            == 1
        )


def test_unconfigured_catalog_and_anonymous_balance(client):
    assert client.get("/api/v1/me/credits").status_code == 401
    catalog = client.get("/api/v1/plans").json()
    assert {r["slug"] for r in catalog} == {"free", "creator", "pro", "business", "topup"}
    assert all(r["price"] is None and not r["auto_renews"] for r in catalog)


def parallel(factory, callbacks):
    barrier = Barrier(len(callbacks))

    def execute(callback):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                value = callback(db)
                db.commit()
                return value
            except ApiError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=len(callbacks)) as executor:
        return list(executor.map(execute, callbacks))


def test_simultaneous_reservations_cannot_overspend(concurrent_db):
    factory, money = concurrent_db
    with factory() as db:
        quotes = [s.make_quote(db, money["alice"], INPUT, f"q{i}").id for i in range(10)]
        db.commit()
    results = parallel(
        factory,
        [
            lambda db, i=i: s.reserve(db, money["alice"], quotes[i], uuid4(), f"r{i}").id
            for i in range(10)
        ],
    )
    assert sum(isinstance(r, UUID) for r in results) == 5
    assert results.count("insufficient_credits") == 5
    with factory() as db:
        assert_wallet(db, money["alice"], 0, 5)


def test_simultaneous_duplicates_grant_settle_refund_once(concurrent_db):
    factory, money = concurrent_db
    uid, admin = money["alice"], money["admin"]
    results = parallel(
        factory, [lambda db: s.adjust(db, uid, 2, "race-grant", admin, REASON, grant=True).id] * 10
    )
    assert len(set(results)) == 1
    with factory() as db:
        row = quote_and_reserve(db, uid)
        rid = row.id
        db.commit()
    results = parallel(
        factory,
        [lambda db: s.finish(db, uid, rid, "settle", success=True, evidence="output").id] * 10,
    )
    assert len(set(results)) == 1
    settled_id = results[0]
    results = parallel(
        factory, [lambda db: s.refund(db, uid, settled_id, 1, "refund", admin, REASON).id] * 10
    )
    assert len(set(results)) == 1
    with factory() as db:
        assert_wallet(db, uid, 7, 0)


def test_settlement_release_race_has_one_winner(concurrent_db):
    factory, money = concurrent_db
    with factory() as db:
        rid = quote_and_reserve(db, money["alice"]).id
        db.commit()
    results = parallel(
        factory,
        [
            lambda db: (
                s.finish(db, money["alice"], rid, "settle", success=True, evidence="output").id
            ),
            lambda db: (
                s.finish(db, money["alice"], rid, "release", success=False, evidence="failure").id
            ),
        ],
    )
    assert sum(isinstance(r, UUID) for r in results) == 1
    assert results.count("reservation_final") == 1
    with factory() as db:
        row = db.get(CreditReservation, rid)
        assert_wallet(db, money["alice"], 4 if row.state == "SETTLED" else 5, 0)


def test_parallel_users_cannot_overspend_global_provider_budget(concurrent_db):
    factory, money = concurrent_db
    with factory() as db:
        reservations = {
            uid: quote_and_reserve(db, uid, str(uid)).id for uid in (money["alice"], money["bob"])
        }
        limits = money["limits"].model_copy(update={"global_daily_usd": Decimal("0.01")})
        s.configure_policy(db, PolicyInput(limits=limits, reason=REASON), "cap", money["admin"])
        db.commit()
    results = parallel(
        factory,
        [
            lambda db, uid=uid, rid=rid: (
                s.admit_spend(db, uid, rid, money["rates"]["deepgram"], 1, "call")[0].id
            )
            for uid, rid in reservations.items()
        ],
    )
    assert sum(isinstance(r, UUID) for r in results) == 1
    assert results.count("budget_exceeded") == 1
    with factory() as db:
        assert db.scalar(select(func.sum(SpendAttempt.estimated_usd))) == Decimal("0.01")


def test_populated_financial_migration_cannot_be_downgraded(concurrent_db):
    factory, money = concurrent_db
    with factory() as db:
        config = Config("alembic.ini")
        config.attributes["connection"] = db.connection()
        with pytest.raises(RuntimeError, match="Refusing to downgrade"):
            command.downgrade(config, "39bc6d102a49")
        assert_wallet(db, money["alice"], 5, 0)


def test_disabled_account_can_release_and_record_sunk_cost(app, money):
    with app.state.session_factory() as db:
        uid = money["alice"]
        row = quote_and_reserve(db, uid)
        attempt, _ = s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 1, "call")
        db.get(User, uid).status = "disabled"
        db.flush()
        with pytest.raises(ApiError) as exc:
            s.admit_spend(db, uid, row.id, money["rates"]["deepgram"], 1, "new-call")
        assert exc.value.code == "account_unavailable"
        s.record_spend(db, uid, attempt.id, units=1, outcome="failure", evidence="provider-usage")
        s.finish(db, uid, row.id, "release", success=False, evidence="disabled")
        wallet = s.lock_wallet(db, uid, active_required=False)
        assert (wallet.available, wallet.reserved) == (5, 0)


def test_expired_quote(app, money, monkeypatch):
    with app.state.session_factory() as db:
        q = s.make_quote(db, money["alice"], INPUT, "expires")
        now = utcnow()
        monkeypatch.setattr(s, "utcnow", lambda: now + timedelta(minutes=16))
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], q.id, uuid4(), "expired")
        assert exc.value.code == "quote_expired"


@pytest.mark.parametrize(
    "field, expected",
    [
        ("daily_credits", "usage_limit"),
        ("monthly_credits", "usage_limit"),
        ("max_concurrent_jobs", "concurrency_limit"),
    ],
)
def test_credit_usage_caps_include_held_jobs(app, money, field, expected):
    with app.state.session_factory() as db:
        rules = money["rules"].model_copy(update={field: 1})
        plan_id = db.get(PlanPrice, money["prices"]["free"]).plan_id
        s.configure_plan(
            db,
            plan_id,
            PlanVersionInput(
                price_paisa=0, included_credits=0, valid_days=0, rules=rules, reason=REASON
            ),
            "limited",
            money["admin"],
        )
        first = quote_and_reserve(db, money["alice"], "first")
        q = s.make_quote(db, money["alice"], INPUT, "second")
        with pytest.raises(ApiError) as exc:
            s.reserve(db, money["alice"], q.id, uuid4(), "r2")
        assert exc.value.code == expected
        s.finish(db, money["alice"], first.id, "release", success=False, evidence="failed")
        s.reserve(db, money["alice"], q.id, uuid4(), "r2")
        assert_wallet(db, money["alice"], 4, 1)


def test_rates_token_limits_attempt_cap_and_zero_cost_evidence(app, money):
    with app.state.session_factory() as db:
        row = quote_and_reserve(db, money["alice"])
        with pytest.raises(ApiError) as exc:
            s.admit_spend(
                db, money["alice"], row.id, money["rates"]["gemini_output"], 11, "too-many"
            )
        assert exc.value.code == "rate_limit"
        with pytest.raises(ApiError) as exc:
            s.configure_policy(
                db,
                PolicyInput(
                    limits=money["limits"].model_copy(
                        update={"rate_ids": [money["rates"]["deepgram"]]}
                    ),
                    reason=REASON,
                ),
                "missing",
                money["admin"],
            )
        assert exc.value.code == "rates_unconfigured"
        limits = money["limits"].model_copy(update={"max_attempts_per_job": 1})
        s.configure_policy(
            db, PolicyInput(limits=limits, reason=REASON), "one-attempt", money["admin"]
        )
        attempt, _ = s.admit_spend(
            db, money["alice"], row.id, money["rates"]["deepgram"], 1, "call"
        )
        s.record_spend(
            db, money["alice"], attempt.id, units=0, outcome="failure", evidence="not-billed"
        )
        with pytest.raises(ApiError) as exc:
            s.admit_spend(db, money["alice"], row.id, money["rates"]["deepgram"], 1, "retry")
        assert exc.value.code == "attempt_limit"
        assert db.scalars(select(ProviderUsage)).one().actual_usd == 0


def test_settlement_transaction_failure_restores_hold(app, money):
    with app.state.session_factory() as db:
        rid = quote_and_reserve(db, money["alice"]).id
        db.commit()
    with app.state.session_factory() as db, pytest.raises(IntegrityError):
        s.finish(db, money["alice"], rid, "settle", success=True, evidence="output")
        db.add(User(email="invalid", role="owner"))
        db.flush()
    with app.state.session_factory() as db:
        assert_wallet(db, money["alice"], 4, 1)
        assert db.get(CreditReservation, rid).state == "HELD"
        s.finish(db, money["alice"], rid, "settle", success=True, evidence="output")
        assert_wallet(db, money["alice"], 4, 0)


def test_float_money_and_frontend_overrides_rejected():
    with pytest.raises(ValidationError):
        RateInput(
            component="deepgram",
            model="test",
            unit="minute",
            unit_usd=0.1,
            max_units=1,
            reason=REASON,
        )
    for duration in (1.1, True, "60"):
        with pytest.raises(ValidationError):
            QuoteInput(source_seconds=duration, output_count=1)
    with pytest.raises(ValidationError):
        RateInput(
            component="deepgram",
            model="test",
            unit="minute",
            unit_usd="0",
            max_units=1,
            reason=REASON,
        )


def test_customer_cannot_use_internal_staff_operations(app, money):
    with app.state.session_factory() as db:
        with pytest.raises(ApiError) as exc:
            s.adjust(db, money["alice"], 1000, "escalate", money["alice"], REASON, grant=True)
        assert exc.value.code == "forbidden"
        assert_wallet(db, money["alice"], 5, 0)


def test_credit_contracts_deny_foreign_reservation_and_usage(app, money):
    with app.state.session_factory() as db:
        row = quote_and_reserve(db, money["alice"])
        attempt, _ = s.admit_spend(
            db, money["alice"], row.id, money["rates"]["deepgram"], 1, "call"
        )
        for operation in (
            lambda: s.finish(db, money["bob"], row.id, "foreign", success=True, evidence="output"),
            lambda: s.record_spend(
                db, money["bob"], attempt.id, units=0, outcome="failure", evidence="fake"
            ),
            lambda: s.admit_spend(
                db, money["bob"], row.id, money["rates"]["deepgram"], 1, "foreign"
            ),
        ):
            with pytest.raises(ApiError) as exc:
                operation()
            assert exc.value.code == "not_found"
        assert_wallet(db, money["alice"], 4, 1)
        assert_wallet(db, money["bob"], 5, 0)


def test_all_admin_configuration_routes_roundtrip(client, app, money):
    headers = authenticate(client, app, money["admin"])
    with app.state.session_factory() as db:
        plan_id = db.get(PlanPrice, money["prices"]["creator"]).plan_id
    data = PlanVersionInput(
        price_paisa=12345, included_credits=12, valid_days=30, rules=money["rules"], reason=REASON
    ).model_dump(mode="json")
    result = client.post(f"/api/v1/admin/plans/{plan_id}/versions", headers=headers, json=data)
    assert result.status_code == 200, result.text
    version = result.json()["id"]
    assert (
        client.post(f"/api/v1/admin/plans/{plan_id}/versions", headers=headers, json=data).json()[
            "id"
        ]
        == version
    )
    result = client.post(
        f"/api/v1/admin/users/{money['alice']}/entitlements",
        headers=headers,
        json={"price_version_id": version, "reason": REASON},
    )
    assert result.status_code == 200, result.text
    rate_data = RateInput(
        component="deepgram",
        model="fictional-v2",
        unit="minute",
        unit_usd=Decimal("0.02"),
        max_units=100,
        reason=REASON,
    ).model_dump(mode="json")
    result = client.post("/api/v1/admin/cost-rates", headers=headers, json=rate_data)
    assert result.status_code == 200, result.text
    result = client.post(
        "/api/v1/admin/limits/versions",
        headers=headers,
        json=PolicyInput(limits=money["limits"], reason=REASON).model_dump(mode="json"),
    )
    assert result.status_code == 200, result.text
    authenticate(client, app, money["alice"])
    assert len(client.get("/api/v1/me/entitlements").json()) == 1
    assert client.get("/api/v1/me/credits").json()["available_credits"] == 17


def test_duplicate_expense_admission_is_single_execution_permission(concurrent_db):
    factory, money = concurrent_db
    with factory() as db:
        rid = quote_and_reserve(db, money["alice"]).id
        db.commit()
    results = parallel(
        factory,
        [
            lambda db: s.admit_spend(
                db, money["alice"], rid, money["rates"]["deepgram"], 1, "same-call"
            )[1]
        ]
        * 10,
    )
    assert results.count(True) == 1 and results.count(False) == 9
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SpendAttempt)) == 1
