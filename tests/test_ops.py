import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import test_billing
import test_credits
from sqlalchemy import select

from zoclip.auth.models import AuditLog
from zoclip.ops.report import report, reporting_policy

payments = test_billing.payments
money = test_credits.money


def test_report_requires_staff_and_audits_read(client, app, payments):
    _, users, _ = payments
    query = "?start=2026-10-01T00:00:00Z&end=2026-11-01T00:00:00Z"
    assert client.get("/api/v1/admin/operations" + query).status_code == 401
    test_credits.authenticate(client, app, users["alice"])
    assert client.get("/api/v1/admin/operations" + query).status_code == 403
    test_credits.authenticate(client, app, users["admin"])
    result = client.get("/api/v1/admin/operations" + query)
    assert result.status_code == 200, result.text
    assert result.json()["actual_usd"] == "0"
    assert "database_url" not in result.text and "email" not in result.text
    with payments[0]() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "operations.report_read"))
    assert client.get("/api/v1/admin/operations?start=2026-10-02&end=2026-11-01").status_code == 422


def test_reporting_policy_is_decimal_and_versioned(tmp_path):
    path = tmp_path / "policy.json"
    data = {
        "version": "fictional-unit-test-v1",
        "vps_monthly_usd": "31.00",
        "usd_pkr": "300.00",
        "margin_target": "0.25",
        "rate_source": "Fictional test rate",
    }
    path.write_text(json.dumps(data))
    policy, original = reporting_policy(path)
    assert policy.vps_monthly_usd == Decimal("31")
    path.write_text(json.dumps(data | {"usd_pkr": "301.00"}))
    assert reporting_policy(path)[1] != original
    path.write_text(json.dumps(data | {"usd_pkr": 300.1}))
    with pytest.raises(ValueError, match="decimal strings"):
        reporting_policy(path)


def test_recorded_provider_usage_serializes_exactly(app, money, tmp_path):
    from zoclip.core.db import utcnow
    from zoclip.credits import service

    now = utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with app.state.session_factory() as db:
        reservation = test_credits.quote_and_reserve(db, money["alice"])
        attempt, _ = service.admit_spend(
            db, money["alice"], reservation.id, money["rates"]["deepgram"], 2, "report-call"
        )
        service.record_spend(
            db, money["alice"], attempt.id, units=2, outcome="success", evidence="fictional-usage"
        )
        db.flush()
        result = report(db, start, utcnow(), str(tmp_path))
    payload = json.loads(json.dumps(result))
    assert payload["usage"] == [
        {"component": "deepgram", "unit": "minute", "units": 2, "actual_usd": "0.0200000000"}
    ]
    assert payload["actual_usd"] == "0.0200000000"


def test_report_paid_order_duplicate_fees_and_reversal(payments, tmp_path):
    factory, _, _ = payments
    order_id = test_billing.new_order(payments)
    test_billing.apply(payments, test_billing.notification(payments, order_id, fee_paisa=25))
    test_billing.apply(payments, test_billing.notification(payments, order_id, fee_paisa=25))
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "version": "fictional-v1",
                "vps_monthly_usd": "31",
                "usd_pkr": "300",
                "margin_target": "0.25",
                "rate_source": "Fictional test rate",
            }
        )
    )
    from zoclip.core.db import utcnow

    now = utcnow()
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
    with factory() as db:
        result = report(db, start, end, str(tmp_path), path)
    assert result["gross_paisa"] == 15000 and result["fee_paisa"] == 25
    assert json.loads(json.dumps(result))["gross_paisa"] == 15000
    assert result["economics"]["vps_allocated_usd"] == "31"
    assert result["economics"]["below_target"] is True
    test_billing.apply(payments, test_billing.notification(payments, order_id, status="REFUNDED"))
    with factory() as db:
        result = report(db, start, end, str(tmp_path), path)
    assert result["gross_paisa"] == 15000 and result["reversed_paisa"] == 15000
    assert result["economics"]["margin"] is None


@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 10, 1), datetime(2026, 11, 1)),
        (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)),
    ],
)
def test_report_period_rejected_before_query(start, end, tmp_path):
    with pytest.raises(ValueError):
        report(None, start, end, str(tmp_path))


def test_file_secrets_are_redacted_and_explicit_values_win(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from zoclip.core.config import Settings

    (tmp_path / "database_url").write_text("postgresql+psycopg://file_user@localhost/file_db")
    config = Settings(_env_file=None, _secrets_dir=tmp_path)
    assert "file_db" not in repr(config)
    config = Settings(
        _env_file=None,
        _secrets_dir=tmp_path,
        database_url="postgresql+psycopg://explicit@localhost/explicit",
    )
    assert config.database_url.get_secret_value().endswith("/explicit")


def test_erasure_retains_finances_and_audited_reason(payments):
    from sqlalchemy import func

    from zoclip.auth.models import User
    from zoclip.core.errors import ApiError
    from zoclip.credits.models import CreditTransaction
    from zoclip.ops.models import PrivacyRequest
    from zoclip.ops.privacy import request_erasure

    order_id = test_billing.new_order(payments)
    test_billing.apply(payments, test_billing.notification(payments, order_id))
    factory, users, _ = payments
    with factory() as db:
        with pytest.raises(ApiError):
            request_erasure(db, users["alice"], users["bob"], "Valid test case")
        request_erasure(db, users["admin"], users["alice"], "Valid test case")
        request_erasure(db, users["admin"], users["alice"], "Valid test case")
        user = db.get(User, users["alice"])
        assert user.status == "disabled" and user.email.startswith("erased-")
        assert user.password_hash is None
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 1
        assert db.scalar(select(func.count()).select_from(PrivacyRequest)) == 1
        assert db.scalars(select(PrivacyRequest)).one().reason == "Valid test case"
        with pytest.raises(ApiError, match="different request payload"):
            request_erasure(db, users["admin"], users["alice"], "Different test case")


def test_auth_cleanup_preserves_current_sessions(payments):
    from datetime import timedelta

    from zoclip.auth.models import AuthSession
    from zoclip.core.db import utcnow
    from zoclip.ops.privacy import cleanup_auth

    factory, users, _ = payments
    with factory() as db:
        db.add_all(
            [
                AuthSession(
                    user_id=users["alice"],
                    token_hash="a" * 64,
                    csrf_hash="c" * 64,
                    expires_at=utcnow() - timedelta(seconds=1),
                ),
                AuthSession(
                    user_id=users["alice"],
                    token_hash="b" * 64,
                    csrf_hash="d" * 64,
                    expires_at=utcnow() + timedelta(hours=1),
                ),
            ]
        )
        db.flush()
        cleanup_auth(db)
        sessions = list(db.scalars(select(AuthSession)))
        assert len(sessions) == 1 and sessions[0].token_hash == "b" * 64


def test_monitor_flags_disk_without_enabling_spend(payments, app, monkeypatch):
    import shutil

    from zoclip.credits.models import SystemLimits
    from zoclip.ops.monitor import snapshot

    factory, _, _ = payments
    monkeypatch.setattr(
        "zoclip.ops.report.shutil.disk_usage", lambda _: shutil._ntuple_diskusage(10, 9, 1)
    )
    with factory() as db:
        db.get(SystemLimits, 1).breaker = True
        db.flush()
        result = snapshot(db, app.state.settings)
    assert "disk_headroom_low" in result["alerts"]
    assert result["spending_disabled"] is True
    assert json.loads(json.dumps(result))["alerts"] == result["alerts"]
