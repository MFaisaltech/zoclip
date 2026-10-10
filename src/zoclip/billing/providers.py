"""Mock protocol is ZoClip-specific, never a claim about any merchant signature.

No adapter here makes network calls. Real checkout/refund transports must add durable
dispatch and provider idempotency/reconciliation before activation.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from zoclip.billing.schemas import SandboxNotification
from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


@dataclass(frozen=True)
class VerifiedNotification:
    provider: str
    notification: SandboxNotification
    evidence_hash: str


class PaymentProvider(Protocol):
    name: str
    fee_schedule_version: str

    def create_checkout(self, order_id: UUID) -> str: ...
    def verify_notification(
        self, body: bytes, headers: Mapping[str, str]
    ) -> VerifiedNotification: ...
    def query_transaction(self, reference: str) -> VerifiedNotification | None: ...
    def refund_if_supported(self, reference: str, key: str) -> VerifiedNotification | None: ...


class DisabledProvider:
    name = "disabled"
    fee_schedule_version = "unverified"

    def unavailable(self) -> None:
        raise ApiError(
            503, "payments_disabled", "Merchant payments are not configured or verified."
        )

    def create_checkout(self, order_id: UUID) -> str:
        self.unavailable()
        raise AssertionError("unreachable")

    def verify_notification(self, body: bytes, headers: Mapping[str, str]) -> VerifiedNotification:
        self.unavailable()
        raise AssertionError("unreachable")

    def query_transaction(self, reference: str) -> VerifiedNotification | None:
        self.unavailable()
        return None

    def refund_if_supported(self, reference: str, key: str) -> VerifiedNotification | None:
        self.unavailable()
        return None


class DisabledJazzCashProvider(DisabledProvider):
    name = "jazzcash"


class MockSandboxProvider:
    name = "mock"
    fee_schedule_version = "zoclip-fictional-sandbox-v1"

    def __init__(self, secret: str):
        self._secret = secret.encode()
        # Explicit injected provider evidence for query/refund tests only. This is
        # not an authoritative financial store, and nothing grants from this map.
        self.test_evidence: dict[str, VerifiedNotification] = {}

    def create_checkout(self, order_id: UUID) -> str:
        return "sandbox_" + order_id.hex

    def verify_notification(self, body: bytes, headers: Mapping[str, str]) -> VerifiedNotification:
        stamp = headers.get("x-sandbox-timestamp", "")
        signature = headers.get("x-sandbox-signature", "")
        if not stamp.isascii() or not stamp.isdigit() or not 1 <= len(stamp) <= 12:
            raise ApiError(401, "invalid_payment_signature", "Payment authentication failed.")
        expected = hmac.digest(self._secret, stamp.encode() + b"." + body, "sha256").hex()
        if (
            len(body) > 16384
            or abs(time.time() - int(stamp)) > 300
            or len(signature) != 64
            or not signature.isascii()
            or not hmac.compare_digest(expected, signature)
        ):
            raise ApiError(401, "invalid_payment_signature", "Payment authentication failed.")
        try:
            data = SandboxNotification.model_validate_json(body)
        except ValidationError as exc:
            raise ApiError(422, "invalid_payment_event", "Invalid payment evidence.") from exc
        if data.occurred_at.tzinfo is None or data.occurred_at.timestamp() > time.time() + 60:
            raise ApiError(422, "invalid_payment_event", "Invalid payment evidence timestamp.")
        return VerifiedNotification(self.name, data, hashlib.sha256(body).hexdigest())

    def query_transaction(self, reference: str) -> VerifiedNotification | None:
        return self.test_evidence.get(reference)

    def refund_if_supported(self, reference: str, key: str) -> VerifiedNotification | None:
        # A refund request cannot manufacture a confirmation. Tests explicitly
        # inject independently verified mock-provider reversal evidence.
        evidence = self.test_evidence.get(reference)
        if evidence and evidence.notification.status == "REFUNDED":
            return evidence
        return None


def build_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider == "mock":
        if settings.app_env == "production":
            raise ValueError("Production mock payments forbidden")
        secret = settings.payment_mock_webhook_secret.get_secret_value()
        if len(secret) < 32 or secret.lower().startswith(("change", "placeholder", "set_")):
            raise ValueError("Sandbox webhook secret must be configured privately")
        return MockSandboxProvider(secret)
    if settings.payment_provider == "jazzcash":
        return DisabledJazzCashProvider()
    return DisabledProvider()


def sign_sandbox(data: SandboxNotification, secret: str) -> tuple[bytes, dict[str, str]]:
    """Local fixture helper; no HTTP endpoint exposes signing or simulation."""
    stamp = str(int(time.time()))
    body = json.dumps(data.model_dump(mode="json"), separators=(",", ":")).encode()
    signature = hmac.digest(secret.encode(), stamp.encode() + b"." + body, "sha256").hex()
    return body, {
        "Content-Type": "application/json",
        "X-Sandbox-Timestamp": stamp,
        "X-Sandbox-Signature": signature,
    }
