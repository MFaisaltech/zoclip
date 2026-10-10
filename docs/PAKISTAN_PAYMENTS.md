# Phase 6 prepaid payments and Pakistan merchant onboarding

Status: local ZoClip sandbox implementation; merchant sandbox and live payments
are **NOT LIVE**. Production readiness is **NOT APPROVED**. No merchant account,
approval, real charge/refund, recurring billing, gateway fee or profit is asserted.
The local sandbox gate passes; actual evidence is in PHASE6_VERIFICATION.md.

## Provider boundary and documentation review

The interface exposes create_checkout, verify_notification, query_transaction and
refund_if_supported. MockSandboxProvider is explicitly development/test only.
DisabledJazzCashProvider rejects every operation; it has no guessed endpoints,
merchant signing code, credentials, success callback or recurring payment support.
PAYMENT_PROVIDER=disabled is the default. Selecting jazzcash in non-production
still rejects requests; production requires the disabled setting.
ENABLE_LIVE_PAYMENTS=true is rejected; production forbids mock payments.

Official references checked on 2026-10-10:

- [JazzCash v4.2 documentation](https://sandbox.jazzcash.com.pk/SandboxDocumentation/v4.2/index.html)
  and [API reference](https://sandbox.jazzcash.com.pk/SandboxDocumentation/v4.2/ApiReferences.html)
  returned a request-rejected page.
- [Resources](https://sandbox.jazzcash.com.pk/SandboxDocumentation/v4.2/Resources.html)
  timed out; [merchant onboarding](https://corporateonboarding.jazzcash.com.pk/online-payment)
  also returned a request-rejected page.

Search index excerpts are insufficient to validate a current merchant contract.
The mock HMAC protocol below is ZoClip's own fixture protocol, **not JazzCash's**.
No integration was derived from third-party snippets or old cached signature examples.

Before enabling a named merchant adapter, obtain and review:

1. Business eligibility, signup/KYC documents, merchant approval and settlement
   account requirements directly from the provider. Keep credentials out of chat/Git.
2. Current versioned sandbox/live checkout, authenticated notification and independent
   query specifications; signed-field canonicalization, status semantics, integer
   currency units, reference uniqueness, replay and transport test vectors.
3. Refund/chargeback support and authorization, full/partial limits, idempotency,
   timeouts/unknown outcomes, late-payment and settlement reconciliation rules.
4. Written fee/tax/settlement schedule, supported payment methods and any separately
   approved recurring capability. Fees are **TBD**; no automatic renewal is implemented.
5. Provider-hosted payment UI and supported return/webhook URLs. ZoClip must not
   collect card/PIN/payment-account secrets, or fetch caller-controlled checkout URLs.
6. Authenticated merchant-sandbox evidence for duplicates, mismatches, spoofing,
   delays and reversals, followed by a separately authorized live verification.

A future network checkout requires durable dispatch/idempotency and uncertain-call
reconciliation before activation. The current create_checkout is a deterministic
local reference calculation with no IO. No transaction spans query/refund IO.

## Plans, orders and finances

Existing Free/Creator/Pro/Business/topup identities and audited immutable price
versions are reused. No launch amounts are seeded. Staff configures integer PKR
paisa, included integer credits, quotas and approval via the existing plan routes.
Unapproved versions are sandbox-only; production payment creation remains disabled.
Measured AI/render/storage/gateway costs and business approval must precede pricing
or margin claims. Provider USD expense records remain separate from PKR payments.

Customer creation accepts only a current price_version_id. Free/zero-price/zero-credit
versions cannot be purchased. The order snapshots owner, price version, PKR amount,
credit quantity, access duration, provider and fee schedule version. The selected
price may change later without changing the order. Paid plans are prepaid 30-day
periods, extended sequentially; top-ups grant credits without replacing timed access.
Credits do not expire. There are no automatic renewals or trial grants.

Each order has one immutable checkout reference. Mock references begin sandbox_;
checkout_url is null and the response explicitly identifies development sandbox use.
No hosted gateway URL or real checkout UI exists. A browser return only reads owner
status; query parameters such as status=success cannot mutate money or credits.

Order states: OPEN, EXPIRED, REVIEW, PAID, REFUNDED, CHARGEBACK. Unpaid orders expire
after 30 minutes. Reads report EXPIRED without changing financial history. A verified
payment made before expiry may arrive late and still grant once. A payment made
after expiry enters REVIEW, grants zero and requires an independent provider query
plus staff reason/accept_late to accept. Disabled/unverified owners also enter REVIEW.
PENDING/FAILED notifications never undo an existing paid/reversed state.

Verified provider, order, reference, exact amount/currency and fee bounds must match.
The user/wallet/order lock serializes checkout, grants, reservations and reversals.
Unique provider event IDs use PostgreSQL conflict arbitration even across owners.
Changed payload with a reused event/key returns 409. The verified event, PAID state,
entitlement and append-only GRANT commit atomically. No staff adjustment grants a
payment; no Redis ledger or browser evidence is accepted. Only bounded hashes and
normalized financial fields are retained, not raw bodies, signatures or payment PII.

The immutable mock fee schedule label is zoclip-fictional-sandbox-v1. Mock event
fee_paisa defaults to fictional zero and is stored separately from amount/credits.
This is not a merchant fee estimate. Real fee schedules need a reviewed versioned
binding before activation; no currency conversion or guessed USD cost is added.

## API and authorization

All paths below are under /api/v1; actual DTOs are in openapi.json.

| Method/path | Behavior |
|---|---|
| POST /billing/orders | Verified owner, Origin/CSRF, Idempotency-Key; price_version_id only; 201 CheckoutView |
| GET /billing/orders/{id} | Owner status only; foreign IDs return 404 |
| GET /billing/history | Owner OrderPage; limit 1..100, exclusive owned cursor, next_cursor |
| POST /billing/webhooks/{provider} | Bounded signed ingress; provider authentication replaces browser CSRF |
| GET /admin/payments | Server RBAC; bounded UUID cursor list, audit event on read |
| POST /admin/payments/{id}/reconcile | RBAC, Origin/CSRF, key, reason and optional accept_late; query evidence only |
| POST /admin/payments/{id}/refund | RBAC, Origin/CSRF, key and reason; durable refund intent, no assumed confirmation |

No public simulation/signing endpoint, customer manual grant or automatic refund
request policy is provided. Customer DTOs omit operation keys, hashes, audit reasons,
private provider configuration and risk details. Staff views show reversal exposure.
Order/webhook rate limits use the existing Redis fail-closed limiter and body limit
is 16 KiB. All session, CORS, no-store, secure cookie and sanitized logging rules apply.

## Reversals, risk and reconciliation

Only a verified full REFUNDED/CHARGEBACK event reverses payment. It can arrive before
SUCCEEDED: the terminal reversal prevents any later grant. Duplicate and distinct
reversal events cannot claw back twice. Partial refunds are unsupported and a
different amount is rejected. Revocation appends a record rather than mutating
the existing immutable entitlement; active-plan and renewal queries exclude it.

Recover credits from the fungible available balance up to the unrefunded original
grant. Existing audited grant reversals count toward that cap. Held credits are
not seized. If credits are spent/reserved, store unrecovered_credits and disable the
account; balances never become negative. Already held work can financially finish
or release using existing trusted cleanup, but disabled access blocks new paid work.
Released/later credits do not silently clear the risk record or re-enable access.

Staff refund requests commit UNKNOWN before the provider call. A timeout, crash or
missing confirmation keeps UNKNOWN; replay never calls the provider again. Only a
verified reversal/query confirms it. The local mock query/refund adapter has no
remote transaction store: test_evidence is explicitly injected verified test data,
empty after process restart. It cannot prove a merchant payment. For a local manual
fixture, send the signed event below; production reconciliation is still unavailable.

The reconciliation route records actor, reason, operation key and result plus an
immutable audit event. No evidence grants zero even with accept_late. Debt resolution,
account re-enablement and merchant dispute handling require a separately approved
audited operational policy; this phase provides no unrestricted unblock button.

## Local manual sandbox

Use an isolated development database/API, never customer data. Configure privately:

```text
PAYMENT_PROVIDER=mock
PAYMENT_MOCK_WEBHOOK_SECRET=<privately-generated-random-32-plus-character-key>
ENABLE_LIVE_PAYMENTS=false
```

Never commit the key or print resolved Compose configuration. Restart the local API
after configuration. Configure a fictional positive plan version through staff API,
authenticate a verified customer, then create an order with CSRF and Idempotency-Key.
Keep the returned order ID. The helper reads only that mock order/reference and
sends its signed event to a loopback/isolated local HTTP API:

```sh
python scripts/payment_sandbox.py <order-uuid> SUCCEEDED --event-id local-demo --allow-local-mock
python scripts/payment_sandbox.py <order-uuid> REFUNDED --event-id local-refund --allow-local-mock
```

The same event ID with a changed timestamp/payload is correctly rejected. For an
exact replay, retain and resend the identical body with a fresh signed envelope
(tests do this ten times). The helper never prints the key, signature or raw body.
Missing explicit opt-in rejects before settings/DB/network. API_PUBLIC_URL must be
HTTP with host localhost, 127.0.0.1 or api; proxy discovery and redirects are disabled.

Mock signature headers are X-Sandbox-Timestamp (current Unix seconds) and
X-Sandbox-Signature (hex HMAC-SHA256 of timestamp + '.' + exact body). Envelope
freshness is 300 seconds; event occurred_at is timezone-aware and not over 60 seconds
in the future. Event IDs and durable hashes provide replay safety beyond that window.
No IP allowlist or unauthenticated redirect is treated as proof of payment.
