"""PostgreSQL outbox and transport mocks only; never sends real email."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
import test_credits
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_email_smtp import config

from zoclip.auth.mail_models import MailDelivery
from zoclip.auth.mail_queue import cleanup_mail, deliver_one, enqueue, enqueue_receipt
from zoclip.auth.models import EmailVerificationToken, User
from zoclip.auth.service import issue_email_token
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError

financial_database = test_credits.concurrent_db


def queued(factory, owner):
    with factory() as db:
        user = db.scalar(select(User).where(User.id == owner).with_for_update())
        raw = issue_email_token(db, user, EmailVerificationToken)
        assert enqueue(db, config(), user, "verify-email", raw)
        assert enqueue(db, config(), user, "verify-email", raw)
        row = db.scalar(
            select(MailDelivery).where(
                MailDelivery.user_id == owner, MailDelivery.state == "QUEUED"
            )
        )
        assert raw.encode() not in row.ciphertext and user.email.encode() not in row.ciphertext
        identity = row.id
        db.commit()
        return identity, raw


def test_delivery_is_durable_and_wipes_payload_after_restart(financial_database, monkeypatch):
    factory, users = financial_database
    identity, raw = queued(factory, users["alice"])
    sent = []
    monkeypatch.setattr("zoclip.auth.email.SMTPEmail.send", lambda *args: sent.append(args[1:]))
    restarted = sessionmaker(factory.kw["bind"], expire_on_commit=False)
    assert deliver_one(restarted, config())
    assert not deliver_one(restarted, config())
    assert len(sent) == 1 and sent[0][2] == raw
    with factory() as db:
        row = db.get(MailDelivery, identity)
        assert row.state == "SENT" and row.attempts == 1 and row.ciphertext is None


def test_failures_are_bounded_and_restart_preserves_attempt_count(financial_database, monkeypatch):
    factory, users = financial_database
    identity, _ = queued(factory, users["alice"])
    sent = []

    def fail(*args):
        sent.append(True)
        raise ApiError(503, "email_delivery_failed", "private diagnostic")

    monkeypatch.setattr("zoclip.auth.email.SMTPEmail.send", fail)
    for attempt in range(1, 4):
        assert deliver_one(sessionmaker(factory.kw["bind"], expire_on_commit=False), config())
        with factory() as db:
            row = db.get(MailDelivery, identity)
            assert row.attempts == attempt
            assert row.failure_code == "email_delivery_failed"
            if attempt < 3:
                assert not deliver_one(factory, config())
                row.due_at = utcnow() - timedelta(seconds=1)
                db.commit()
            else:
                assert row.state == "FAILED" and row.ciphertext is None
    assert len(sent) == 3 and not deliver_one(factory, config())


@pytest.mark.parametrize("failure", ["expiry", "consumed", "tampered", "key", "disabled"])
def test_invalid_payloads_fail_closed(financial_database, monkeypatch, failure):
    factory, users = financial_database
    identity, _ = queued(factory, users["alice"])
    settings = config()
    with factory() as db:
        row = db.get(MailDelivery, identity)
        if failure == "expiry":
            row.expires_at = utcnow() - timedelta(seconds=1)
        elif failure == "consumed":
            db.scalar(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.user_id == users["alice"]
                )
            ).consumed_at = utcnow()
        elif failure == "tampered":
            row.ciphertext = b"invalid"
        elif failure == "key":
            settings = config(email_queue_key="eXl5eXl5eXl5eXl5eXl5eXl5eXl5eXl5eXl5eXl5eXk=")
        else:
            db.get(User, users["alice"]).status = "disabled"
        db.commit()
    monkeypatch.setattr(
        "zoclip.auth.email.SMTPEmail.send", lambda *a: pytest.fail("No SMTP dispatch")
    )
    assert deliver_one(factory, settings)
    with factory() as db:
        row = db.get(MailDelivery, identity)
        assert row.state in {"FAILED", "EXPIRED"} and row.ciphertext is None


def test_concurrent_workers_do_not_double_send_and_reclaim_crashed_attempt(
    financial_database, monkeypatch
):
    factory, users = financial_database
    identity, _ = queued(factory, users["alice"])
    with factory() as db:
        row = db.get(MailDelivery, identity)
        row.state, row.attempts = "SENDING", 1
        row.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    entered, finish = Event(), Event()
    sent = []

    def send(*args):
        sent.append(True)
        entered.set()
        assert finish.wait(10)

    monkeypatch.setattr("zoclip.auth.email.SMTPEmail.send", send)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(deliver_one, factory, config())
        assert entered.wait(10)
        second = pool.submit(deliver_one, factory, config())
        try:
            assert second.result(timeout=5) is False
        finally:
            finish.set()
        assert first.result(timeout=10)
    assert len(sent) == 1
    with factory() as db:
        assert db.get(MailDelivery, identity).attempts == 2


def test_superseded_token_cleanup_and_unpaid_receipt_fail_closed(financial_database):
    factory, users = financial_database
    first, _ = queued(factory, users["alice"])
    queued(factory, users["alice"])
    with factory() as db:
        assert db.get(MailDelivery, first).state == "EXPIRED"
        assert db.get(MailDelivery, first).ciphertext is None
        with pytest.raises(ValueError, match="settled"):
            enqueue_receipt(db, config(), first)
        for row in db.scalars(select(MailDelivery)):
            row.expires_at = utcnow() - timedelta(days=8)
        db.commit()
    with factory() as db:
        cleanup_mail(db)
        db.flush()
        cleanup_mail(db)
        assert db.scalar(select(func.count()).select_from(MailDelivery)) == 0


def test_settled_receipt_observer_is_idempotent_and_cannot_grant_credits(
    financial_database, monkeypatch
):
    import test_billing

    from zoclip.auth.mail_queue import enqueue_recent_receipts
    from zoclip.billing.providers import MockSandboxProvider
    from zoclip.credits.models import CreditTransaction

    factory, users = financial_database
    test_billing.configure(factory, users)
    payments = factory, users, MockSandboxProvider(test_billing.SECRET)
    order_id = test_billing.new_order(payments)
    assert test_billing.apply(payments, test_billing.notification(payments, order_id)) == "PAID"
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(CreditTransaction))
        enqueue_recent_receipts(db, config())
        enqueue_recent_receipts(db, config())
        assert db.scalar(select(func.count()).select_from(MailDelivery)) == 1
        db.commit()
    sent = []
    monkeypatch.setattr(
        "zoclip.auth.email.SMTPEmail.send_receipt", lambda *args: sent.append(args[1:])
    )
    assert deliver_one(factory, config())
    assert not deliver_one(factory, config())
    assert sent[0][1:] == (str(order_id), 15000, 10)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == before


def test_account_erasure_wipes_queued_email(financial_database):
    from zoclip.ops.privacy import request_erasure

    factory, users = financial_database
    identity, _ = queued(factory, users["alice"])
    with factory() as db:
        request_erasure(db, users["admin"], users["alice"], "Owner erasure regression")
        db.commit()
    with factory() as db:
        assert db.get(MailDelivery, identity).ciphertext is None
        assert db.get(MailDelivery, identity).state == "EXPIRED"
