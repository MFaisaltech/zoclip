# Phase 8, Milestone 5 — billing and administration

2026-10-14: product implementation complete with focused offline verification.
Live AI acceptance is paused until private staging. Its evidence, guards and
approvals were not modified.

`billing/dashboard.py` adds owner-scoped applied-plan/usage and reservation reads,
admin customer search/balances, customer usage, aggregate financial overview and
bounded staff job views. Reads reuse `active_price` and the exact reservation
quota semantics: all HELD exposure plus period-relevant SETTLED credits; RELEASED
credits are excluded. Default free access is labeled separately from an actual
entitlement. No subscription is inferred from a balance. Customer data is scoped
from `CurrentUser`; staff data requires `AdminUser` and staff reads are audited.
Private job payloads/checkpoints are never returned.

No financial write route or service was replaced. The UI reuses existing audited
plan versions, credit adjustments and staff access grants, with CSRF/reasons and
idempotency. Ledger rules, budget policies, rates, AI configuration and payment
adapters are unchanged. The new checkout capability is explicitly false: no
merchant integration or new price/allocation is invented or installed. No schema
migration or environment variable is introduced.

The frontend provides `/billing`, `/admin`, pricing/upgrade review, real balances,
transactions, reservations, prepaid access, customers, plans, jobs, costs,
uncertain spend, read-only limits, sandbox payments and audit views. See
`../../frontend/BILLING_ADMIN_INTEGRATION.md` for files, endpoints, request recovery,
verification and remaining staging/payment decisions.

Focused checks:

- Six real PostgreSQL dashboard cases pass in newly created, preserved mock
  schemas; no reset, downgrade or drop. Final evidence:
  `var/m5-final-a594d4308dc14e5e8b02dc449c57dcbd/results.xml`.
- Ten configuration/OpenAPI checks passed with the initial five dashboard cases:
  `var/m5-focused-b5ffb301070a4b80be55b7977f8a16c6/results.xml`.
- 32 frontend billing/media/workspace cases pass; TypeScript, focused lint and
  generated contract drift checks pass. Focused backend Ruff/format/mypy pass.
- Existing two HTTPX deprecation warnings remain. An initial test invocation
  lacked its temporary parent directory; the successful invocations used fresh
  evidence directories and the required local Windows test access.

Runtime and acceptance schemas were not written. No live provider or payment
request, deployment, commit or push. Production build, responsive browser QA and
private TLS/cookie/CSRF/RBAC configuration verification remain for private staging
on a host with adequate memory. Commercial and merchant decisions remain pending.
