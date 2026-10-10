"""Sign/send a local mock event. Requires private env key and explicit local opt-in.

Not a gateway client, signing service, hosted checkout or production refund tool.
"""

import argparse
import json
import urllib.request
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from zoclip.billing.models import BillingOrder, PaymentAttempt
from zoclip.billing.providers import sign_sandbox
from zoclip.billing.schemas import SandboxNotification
from zoclip.core.config import Settings
from zoclip.core.db import build_engine, utcnow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id", type=UUID)
    parser.add_argument(
        "status", choices=["PENDING", "FAILED", "SUCCEEDED", "REFUNDED", "CHARGEBACK"]
    )
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--allow-local-mock", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_mock:
        parser.error("--allow-local-mock is required")
    settings = Settings()  # type: ignore[call-arg]
    url = urlsplit(settings.api_public_url)
    if (
        settings.app_env not in {"development", "test"}
        or settings.payment_provider != "mock"
        or url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1", "api"}
    ):
        raise RuntimeError("Explicit mock mode and a local isolated HTTP API are required")
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as db:
            order = db.get(BillingOrder, args.order_id)
            if not order or order.provider != "mock":
                raise RuntimeError("Mock order not found")
            reference = db.scalars(
                select(PaymentAttempt.reference).where(PaymentAttempt.order_id == order.id)
            ).one()
            event = SandboxNotification(
                event_id=args.event_id or "local-" + uuid4().hex,
                order_id=order.id,
                reference=reference,
                status=args.status,
                amount_paisa=order.amount_paisa,
                currency=order.currency,
                occurred_at=utcnow(),
            )
        body, headers = sign_sandbox(event, settings.payment_mock_webhook_secret.get_secret_value())
        request = urllib.request.Request(
            settings.api_public_url + "/api/v1/billing/webhooks/mock", data=body, headers=headers
        )

        # No proxy discovery or redirects: private signature stays at this local API.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
                return None

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=10) as response:
            result = json.load(response)
        print(json.dumps({"order_id": result["id"], "state": result["state"]}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
