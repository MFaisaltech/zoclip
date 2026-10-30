# Manual purchases and 50-credit clip pricing

Implemented for review on existing feature branches; no live deployment, catalog
installation, payment, balance change or generation activation is part of this work.

## Customer flow

Only two packages are offered: Creator PKR 1,000 (100,000 paisa) for 10,000 credits,
and Pro PKR 2,000 (200,000 paisa) for 21,000 credits. Both are non-renewing prepaid
credit packages without timed expiry. Each delivered clip is 50 credits, including
captions and framing; source duration adds no credits. Existing duration, capacity,
account and expense-policy checks still apply. Re-exports need a fresh 50-credit
one-output quote; legacy prepaid-edit quotes keep their old behavior.

Buy via WhatsApp opens `https://wa.me/923189753773` with the selected package,
price and credits, asks for verified payment instructions before payment, and
requests the registered email, screenshot and transaction reference. No bank or
wallet account details are invented. Clicking a link never creates a paid order,
entitlement or credit grant. The customer must send the message themselves.

## Staff flow and protections

Admin > Purchases searches an exact registered email, including existing admin
accounts. No account is created. The verifier checks the bank/wallet receipt
independently; a screenshot alone is insufficient. They select current approved
terms, enter the independently verified amount and full transaction reference,
confirm verification and give a permanent audit reason.

`AdminUser`, existing session authentication, CSRF, rate limits and active/verified
staff checks protect the endpoints. `MANUAL_PAYMENTS_ENABLED=false` by default;
manual activation requires a separate explicit enablement. Enabling it requires
gateways disabled, local Whisper/local selection, and no paid AI credentials.

The API checks the exact amount, latest approved purchasable package, recipient
status, and a canonicalized bank/wallet transaction reference. Case/spacing and
separator differences cannot reuse a receipt. A database unique reference claim
serializes concurrent attempts across accounts and request keys. An operation key
is bound to actor, recipient, plan, verified amount/reference and audit reason.
Lost responses reuse the original stored key; they never create another grant.

Order, payment evidence/attestation, entitlement, ledger grant and staff audit
commit together. A rollback grants nothing. Manual records are marked non-sandbox
and remain separate from historical mock gateway records. Reference uniqueness
requires staff to enter the actual full reference consistently; it does not
automatically authenticate a screenshot or replace human verification.

The refund action records a full refund already independently completed outside
ZoClip. It never sends money. It reuses the existing payment reversal: recover
available credits only, preserve holds, revoke access, record unrecovered exposure
and disable an account with debt. No negative wallet, duplicate reversal or
re-grant on replay of a refunded purchase is allowed. Historical records remain.

## Clip settlement

Quotes reserve 50 times the requested output/edit count. On a completed job,
settlement uses its pinned price version and actual completed exports. Any unused
hold is returned by an append-only RELEASE, followed by one SETTLE for delivered
clips. Quota/usage views use actual settlements, not the original larger hold.
Full job failure/cancellation still releases the hold; incomplete jobs' partial
files cannot be downloaded. Historical duration-priced quotes retain their old
settlement and refund semantics. No ledger history is rewritten.

## Review and later rollout

No schema migration is needed. The catalog installer appends new versions and
non-purchasable retirement versions for Starter/Business/top-ups; it does not
delete historical plans, rewrite entitlements or grant any credits. Free is kept
as an internal non-purchasable 50-per-clip default with zero automatic credits;
it is not advertised as an extra package. Historical balances remain untouched.

After separate staging rollout approval, install `deploy/staging-catalog.json`
through the audited catalog installer under an existing active admin UUID. It
requires protected private staging, paused generation, payments/trials disabled,
and breaker=true. Example inside the API image, with JSON streamed on stdin:

```sh
python -m zoclip.ops.catalog - --actor <existing-admin-uuid> --execute
```

The deployment controller does not automatically include
`deploy/compose.manual-payments.yaml`. Only after separate approval may that
overlay enable the manual API. Keep `AI_ENABLED=false`,
`STAGING_GENERATION_ENABLED=false`, an empty staging test-account UUID,
`PAYMENT_PROVIDER=disabled`, live payments/trials disabled and private networking.
This does not configure an expense policy or enable generation.

Rollback by removing the optional manual overlay and restoring the previous
protected frontend alias/image. Preserve all purchase/refund/credit records.
Append reviewed replacement catalog versions if terms need correction; do not
delete versions or restore a backup over financial history. Existing paid manual
orders remain auditable even with manual activation disabled.

## Focused verification — 2026-10-30

Passed across focused runs (no repeated full suite): 25 backend cases and 22
frontend unit cases, plus three browser cases covering desktop/mobile pricing,
WhatsApp links and the admin verification form. Real PostgreSQL tests cover
cross-account concurrent receipt reuse, idempotent activation, request keys up to
128 characters, staff authorization, CSRF, amount/version checks, atomic rollback,
refund exposure and holds, unused-hold release, settlement replay and historical
duration-priced purchases. The worker fixture uses simulated local transcription
and actual FFmpeg output: one delivered clip from three quoted settles 50 and
releases 100, with no charge on redelivery. It is not another Whisper benchmark.

Historical pricing research reads its archived catalog explicitly, while the
current catalog quote smoke returns 50 without any credit grant and retains the
spending breaker. Frontend lint, TypeScript, API/pricing contract checks, backend
lint/type checks and the isolated Next.js 16.4.1 production build passed. Browser
API responses were fixtures; PostgreSQL and build/browser containers had no
externally routed network. No real payment, paid API or deployment was performed.
