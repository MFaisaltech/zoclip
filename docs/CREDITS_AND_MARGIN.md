# Credits, plans and expense admission — Phase 2

PostgreSQL is authoritative. Phase 2 supplies accounting contracts and API routes;
there are no processing jobs, paid provider adapters, payments or uploads yet.
No retail price, real model ID, provider rate, margin or benchmark is asserted.
The migration seeds Free, Creator, Pro, Business and one configurable top-up
catalog entry **without any price versions, allowances or rates**. The initial
expense circuit breaker is open. Empty configuration cannot authorize paid work.

## Customer accounting

Credits and PKR paisa are separate integers. USD uses Decimal and PostgreSQL
NUMERIC (rates 20,10; expense holds/actual costs 30,10). Financial inputs reject
floating-point USD values; use decimal strings. Every credit mutation acquires
the target user row, then its unique wallet row with SELECT FOR UPDATE. Wallets
are provisioned lazily under that lock; an untouched account has zero credits.
The service checks reconciliation before mutations, updates materialized balances
and appends a ledger row in the **same caller-owned transaction**. CHECK constraints
reject negative available/reserved balances and invalid ledger operation deltas.
Financial FKs do not cascade-delete history.

| Operation | Available delta | Reserved delta | Authority |
|---|---:|---:|---|
| GRANT | +n | 0 | Explicit audited staff grant or plan allowance; no payment claims |
| RESERVE | -n | +n | Trusted internal job contract after validating the source |
| SETTLE | 0 | -n | Trusted worker, verified successful deliverable reference |
| RELEASE | +n | -n | Trusted worker, durable final failure/cancellation reference |
| REFUND of SETTLE | +n | 0 | Staff-authorized correction, capped by original settled charge |
| REFUND of GRANT | -n | 0 | Staff-authorized grant reversal, capped by grant and spendable funds |
| ADMIN_ADJUST | signed n | 0 | Active verified admin and meaningful private reason |

REFUND is credit accounting, not a gateway currency refund. It references its
original ledger entry; cumulative refunds cannot exceed that entry. Reversal
cannot consume reserved credits or create negative funds. Currency chargeback
evidence, account risk holds and payment/refund workflows belong to Phase 6.

Reservations have a globally unique job UUID and a single-use quote UUID.
HELD may become SETTLED **or** RELEASED once. A transient retry keeps its hold;
only final failure releases it. Customer charging is whole-job success only.
Different keys cannot settle/release a finalized reservation again. An identical
key/payload returns the prior record; changing payload under a key returns 409.
Credit keys are scoped to the owner across all ledger operations. Quote keys are
scoped to owner; expense keys to reservation; configuration keys to plan/component
or the global policy. Use opaque keys, never PII. Retries must retain their keys.

PostgreSQL triggers reject UPDATE, DELETE and TRUNCATE on wallet_transactions,
credit_quotes, plan_price_versions, user_entitlements, cost_rate_versions,
cost_policy_versions and provider_usage. Existing admin audit triggers remain.
Schema owners/superusers can bypass protections; least-privilege migration/runtime
roles remain a deployment requirement. Migration downgrade refuses populated
credit-ledger or expense-attempt history; use forward fixes and backups.

## Plan and allowance lifecycle

Staff creates immutable, reasoned price versions through the API. Each records
PKR paisa, included credits, explicit consumption rules and approval status.
Unapproved configurations are clearly marked in the catalog and cannot produce
new production quotes/reservations. Test values are fictional, not launch prices.
Paid access is **prepaid 30 days**, never automatic recurring billing. Free access
and top-ups have no timed access period. A top-up adds credits without replacing
the current plan. Active paid access takes precedence over a Free allowance.

The staff entitlement award is an explicit manual benefit, **not a purchase**.
Each award grants included credits exactly once in its transaction. Distinct
early renewals schedule access consecutively after outstanding paid access;
included credits are awarded immediately and carry over. There is no prorated
upgrade/downgrade flow. When access expires, current Free rules apply (or admission
fails if Free is unconfigured); unused wallet credits remain. Existing entitlements
pin their immutable price/rules version; changing catalog prices does not rewrite
prior awards. Free allowance can be manually awarded once per account even across
versions. Repeating a staff operation key does not grant a second allowance.

**Credit expiry is disabled, with unrestricted rollover.** No EXPIRE operation or
cleanup destroys credits. A future expiry policy needs disclosure and a reviewed
migration. Automatic trials remain disabled: ENABLE_TRIAL_CREDITS=true is rejected
until device/IP heuristics and abuse review controls exist. Verified email and
rate limits alone are not sufficient to enable automatic grants. There is no
customer claim-grant, purchase-success, grant or adjustment endpoint.

## Quote and usage rules

POST /api/v1/jobs/quote requires authentication, Origin/CSRF, Idempotency-Key and
a bounded QuoteInput. It stores a free, versioned 15-minute quote. Repeat requests
return that same quote, including its original expiry, and never charge credits.

```text
credits = ceil(source_seconds / 60) * credits_per_minute
        + output_count * credits_per_output
        + edit_count * credits_per_edit
        + (captions ? captions_credits : 0)
        + (reframe ? reframe_credits : 0)
```

Every factor is server-configured. Positive source-minute credits prevent zero-price
unbounded work. Source duration is capped at 7200 seconds and smaller plan limits;
outputs/edits have explicit plan caps. Reservation rejects expired/stale quotes,
insufficient balance, per-user concurrency/credit quotas and global outstanding
reservation capacity. Daily/monthly credit usage is UTC: held jobs count regardless
of age; settled work counts by admission or finalization time. Released failures
restore customer allowance, whereas refunded successful work still counts as work
performed. Period totals are derived from reservations under the user lock.

Source seconds submitted to this advisory endpoint are not proof of media duration.
Phase 3 must derive/revalidate the complete quote request from owned, probed source
metadata and persist the requested features/output/edit limits on its job. Never
accept a client's credit amount or enqueue based solely on an advisory quote.

## Expense protection

Staff configures immutable rates for Deepgram minutes, Gemini input/output tokens,
render CPU-seconds and storage GB-days, with model/allocator labels and max units.
All five correctly dimensioned, positive rates are required. These are accounting
inputs, not implemented provider integrations or claims of real billing units.
Future adapters must convert provider usage conservatively and use current official
paid rates for the configured model/add-ons. No reliance on promotional free quotas.

The active versioned policy contains per-job, per-user daily/monthly and global
daily/monthly USD ceilings; model token assumptions; render/storage assumptions;
max outstanding reservations; and retry-attempt cap. Missing rates/policy, an open
breaker, invalid/beyond-cap usage or insufficient budget fails closed with 503.
A zero budget disables any positive expense. No environment-only budget can bypass
the database policy; configuration changes and expense admission lock system_limits.

Whole-job preflight sums configured conservative duration/token/render/storage
estimates and checks budget availability. Before **each** expense, admit_spend
locks user/wallet then system_limits and atomically stores a spend hold against
all budget dimensions. It includes other users' global exposure. This single global
mutex is intentional for the initial monolith; measure before changing it. Queries
aggregate in PostgreSQL. Different jobs may pass preflight and later be denied
paid-call admission when other jobs consume capacity; preflight is not a guaranteed
future expense allocation.

admit_spend returns (attempt, fresh). Only fresh=True, after successful commit, may
permit execution. A duplicate returns fresh=False even if its first outcome was
lost. HELD/UNKNOWN attempts block another expense on that job until reconciled.
Timeout/crash does not prove a free failure; retain exposure and never blindly
retry. Unknown/in-flight holds count in every current daily/monthly period even
across calendar boundaries. Known costs are conservatively counted by admission
or recording time. Each retry gets a new attempt after evidence resolves the prior
one; prior sunk costs remain in budgets.

record_spend checkpoints actual units, pinned-rate cost, outcome and an opaque
evidence reference in append-only provider_usage. No transcripts, credentials or
provider raw responses are stored here. Actual expense greater than its estimate
is recorded **and opens the breaker**. Unknowns remain held. Proven non-billable
failure records zero; customer failure/release never erases provider costs. Disabled
accounts cannot start new expense, but finalization and cost reconciliation still
work. Admin usage metrics show estimated, actual and unresolved expense separately.
Real provider response/checkpoint storage and reconciliation tooling arrive in
later phases; there is no automatic reconciler or exactly-once remote billing claim.

## Integration contract for Phase 3 and later

All service functions flush but never commit, call a provider, enqueue or operate
files. Use one Session per request/task. On any exception roll back the **entire**
transaction. Do not reuse a failed transaction or keep it open across network work.

1. Validate owned source and request; compute/revalidate quote with authoritative
   duration. In one transaction create the future job/outbox and call reserve.
2. Commit the expense admission before a paid side effect. On replay inspect its
   durable checkpoint rather than executing again. Network/FFmpeg runs outside DB
   locks. Actual retry costs consume the same job/user/global ceilings.
3. In a fresh transaction record expense and output/provider checkpoints. Unknown
   remote outcomes need independent evidence before retrying or freeing exposure.
4. After verifying the requested deliverable, atomically persist job/output terminal
   state and call finish(success=True). Final failure/cancel calls finish(False).
   Do not call finish based on customer input or a queue notification alone.
5. Use stable keys/evidence. Reconciliation failure blocks the account's financial
   actions. Media/outbox/leases/checkpoints and cleanup are **not** Phase 2 features.

## Economics and verification limits

Only configured expense estimates and recorded usage exist. There are no measured
Gemini/Deepgram invoices, render/storage benchmarks, payment fees or PKR revenue.
Rendering/storage rates are conservative allocation assumptions, not invoices.
Margin also needs failed-job costs, infrastructure, storage retention, gateway fees,
tax/refunds, exchange rates and approved retail prices. No guaranteed profit or
economically validated plan is claimed. Profit/revenue reports await those inputs.

Run the complete suite against a disposable PostgreSQL database ending in _test
and Redis DB 15 (README commands). tests/test_credits.py covers real independent
transactions, overspend/duplicates/races, rollback, owner isolation, immutable
history, allowances, quotes and all expense-budget dimensions without providers.
Concurrency tests migrate isolated schemas and drop only their generated schemas;
they never disable immutability triggers. See IMPLEMENTATION_STATUS.md for exact
commands and observed results rather than inferring verification from test files.
