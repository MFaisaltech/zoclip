"""Opt-in isolated development HTTP sandbox smoke; no merchant calls or money."""

import os
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from zoclip.auth.models import AuthSession, User
from zoclip.billing.models import BillingOrder, PaymentEvent
from zoclip.billing.providers import sign_sandbox
from zoclip.billing.schemas import SandboxNotification
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow
from zoclip.core.security import COOKIE_NAME, digest
from zoclip.credits.models import Plan
from zoclip.credits.schemas import ConsumptionRules, PlanVersionInput
from zoclip.credits.service import configure_plan, lock_wallet, reconcile


def main() -> None:
    if os.environ.get("ZOCLIP_PAYMENT_SANDBOX_SMOKE") != "1":
        raise RuntimeError("ZOCLIP_PAYMENT_SANDBOX_SMOKE=1 is required before DB/network")
    settings = Settings()  # type: ignore[call-arg]
    if settings.app_env != "development" or settings.payment_provider != "mock":
        raise RuntimeError("Isolated development mock payment configuration required")
    engine = build_engine(settings.database_url.get_secret_value())
    owner_token, other_token, csrf = (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
    )
    try:
        with Session(engine) as db:
            admin = User(
                email=f"sandbox-staff-{uuid4()}@example.invalid", verified=True, role="admin"
            )
            owner = User(email=f"sandbox-buyer-{uuid4()}@example.invalid", verified=True)
            other = User(email=f"sandbox-other-{uuid4()}@example.invalid", verified=True)
            db.add_all([admin, owner, other])
            db.flush()
            for user, token in ((owner, owner_token), (other, other_token)):
                db.add(
                    AuthSession(
                        user_id=user.id,
                        token_hash=digest(token),
                        csrf_hash=digest(csrf),
                        expires_at=utcnow() + timedelta(minutes=10),
                    )
                )
            plan = db.scalars(select(Plan).where(Plan.slug == "creator")).one()
            price = configure_plan(
                db,
                plan.id,
                PlanVersionInput(
                    price_paisa=15000,
                    included_credits=10,
                    valid_days=30,
                    rules=ConsumptionRules(
                        credits_per_minute=1,
                        credits_per_output=0,
                        credits_per_edit=0,
                        captions_credits=0,
                        reframe_credits=0,
                        max_source_seconds=7200,
                        max_outputs=10,
                        max_edits=5,
                        max_concurrent_jobs=1,
                        daily_credits=100,
                        monthly_credits=1000,
                    ),
                    reason="Explicit isolated fictional sandbox smoke price",
                ),
                "sandbox-" + uuid4().hex,
                admin.id,
            )
            db.commit()
            owner_id, price_id = owner.id, price.id
        with httpx.Client(base_url=settings.api_public_url, timeout=15, trust_env=False) as client:
            client.cookies.set(COOKIE_NAME, owner_token)
            headers = {
                "Origin": settings.public_app_url,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "sandbox-purchase",
            }
            response = client.post(
                "/api/v1/billing/orders", headers=headers, json={"price_version_id": str(price_id)}
            )
            assert response.status_code == 201, response.status_code
            checkout = response.json()
            order_id = UUID(checkout["order"]["id"])
            path = f"/api/v1/billing/orders/{order_id}"
            assert client.get(path + "?status=success").json()["state"] == "OPEN"
            assert client.get("/api/v1/me/credits").json()["available_credits"] == 0
            assert settings.payment_mock_webhook_secret.get_secret_value() not in response.text
            event = SandboxNotification(
                event_id="sandbox-success-" + uuid4().hex,
                order_id=order_id,
                reference=checkout["reference"],
                status="SUCCEEDED",
                amount_paisa=15000,
                currency="PKR",
                occurred_at=utcnow(),
                fee_paisa=25,
            )
            body, signed = sign_sandbox(
                event, settings.payment_mock_webhook_secret.get_secret_value()
            )
            forged = signed | {"X-Sandbox-Signature": "0" * 64}
            assert (
                client.post(
                    "/api/v1/billing/webhooks/mock", content=body, headers=forged
                ).status_code
                == 401
            )
            assert client.get("/api/v1/me/credits").json()["available_credits"] == 0

            def deliver(_):
                with httpx.Client(
                    base_url=settings.api_public_url, timeout=15, trust_env=False
                ) as sender:
                    result = sender.post(
                        "/api/v1/billing/webhooks/mock", content=body, headers=signed
                    )
                    assert result.status_code == 200, result.status_code
                    assert result.json()["state"] == "PAID"

            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(deliver, range(10)))
            assert client.get("/api/v1/me/credits").json()["available_credits"] == 10
            assert client.get("/api/v1/admin/payments").status_code == 403
            client.cookies.set(COOKIE_NAME, other_token)
            assert client.get(path).status_code == 404
            assert client.get("/api/v1/billing/history").json()["items"] == []
            client.cookies.set(COOKIE_NAME, owner_token)
            print(
                "PASS: order, spoof/redirect zero, ten concurrent deliveries grant once, isolation"
            )
            helper = Path(__file__).with_name("payment_sandbox.py")
            subprocess.run(
                [sys.executable, str(helper), str(order_id), "REFUNDED", "--allow-local-mock"],
                check=True,
            )
            assert client.get(path).json()["state"] == "REFUNDED"
            assert client.get("/api/v1/me/credits").json()["available_credits"] == 0
        with Session(engine) as db:
            row = db.get(BillingOrder, order_id)
            assert row.grant_id and row.entitlement_id
            assert (
                len(list(db.scalars(select(PaymentEvent).where(PaymentEvent.order_id == order_id))))
                == 2
            )
            reconcile(db, lock_wallet(db, owner_id))
        print(
            "PASS: sandbox helper, verified refund, entitlement revocation, ledger reconciliation"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
