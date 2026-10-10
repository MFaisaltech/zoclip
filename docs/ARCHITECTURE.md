# ZoClip architecture blueprint

Status: Phase 0 design with Phase 1 foundation and Phase 2 accounting implemented; see
IMPLEMENTATION_STATUS.md for evidence and remaining gates. The master specification is the product contract. This document
selects implementation defaults; capacity figures below are planning limits, not
benchmarks. Frontend and phases 3–8 remain unimplemented. The Phase 2 transaction
contracts, limits and implemented scope are detailed in CREDITS_AND_MARGIN.md.

## Components and boundaries

```text
Later Next.js/v0 frontend
        | HTTPS, session cookie + CSRF
        v
Nginx -> FastAPI modular monolith -> PostgreSQL
              |                       | durable dispatch outbox
              |                       v
              +-----------------> dispatcher -> Redis/RQ
                                               | ai queue: 1 worker
                                               | render queue: 1 worker
Workers -> PostgreSQL checkpoints/ledger/budgets; private local storage
AI worker -> Deepgram (audio), Gemini (transcript text)
Render worker -> constrained FFmpeg/ffprobe and sampled CPU face detection
Scheduler -> cleanup, reconciliation, recovery, outbox dispatch
```

Only Nginx exposes production ports 80/443. Database and Redis have private
Compose networking and persistent volumes; no public host ports. API and workers
share code but use separate processes and short synchronous DB transactions.
No DB transaction remains open during network requests or media processing.
RQ is at-least-once transport: PostgreSQL owns job identity and lifecycle.
An outbox row committed with job creation/reservation closes the DB-to-Redis gap.
Dispatcher retries safely; worker claims use locked rows and lease/fencing tokens.
Expired leases require checkpoint inspection before replay; stale workers cannot
commit results or settle money. Recovery must not release credits while a live
worker can still commit a deliverable.

## Proposed repository and dependencies

```text
src/zoclip/
  main.py
  core/        # settings, errors, logging, security, DB, observability
  auth/        # users, sessions, email tokens, OIDC, permission helpers
  credits/     # wallets, ledger, quotes, reservations, reconciliation
  plans/       # versioned prices, entitlements, quotas
  billing/     # orders, events, adapters, refunds
  media/       # storage, uploads, SSRF-safe imports, probe, retention
  jobs/        # state machine, outbox, leases, checkpoints, recovery
  providers/   # Deepgram/Gemini interfaces, cache, usage, spend admission
  clips/       # suggestions, revisions, captions, reframe, render outputs
  admin/       # RBAC, audited limits, reporting
  workers/     # RQ entrypoints, dispatcher, scheduler
alembic/versions/
tests/{unit,integration,security,contract,fixtures}/
deploy/        # Compose, Nginx, operational scripts in later phases
docs/
```

Each domain owns routes, Pydantic schemas, SQLAlchemy models and service logic;
routes do not implement financial mutations. Shared services mediate cross-domain
transactions. Avoid a framework-heavy repository abstraction.

Constraints: Python >=3.12,<3.13; Pydantic >=2,<3; SQLAlchemy >=2,<3;
psycopg >=3,<4; Alembic >=1,<2. FastAPI, RQ, redis-py, Authlib, argon2-cffi,
httpx, settings library, pytest, Ruff and mypy require compatible maintained
versions selected and locked in Phase 1. No guessed current package versions.
Official Deepgram/Google SDK versions and model IDs are selected against current
official docs in Phase 4. Ubuntu FFmpeg/ffprobe and OpenCV compatibility is tested
in media phases; record container image digests and binary versions. No dependencies
or lockfile were installed in Phase 0. Phase 1 now provides pyproject.toml and uv.lock;
the resolved environment is recorded in implementation status.

## Database and migration plan

UUID keys; UTC timestamps; FK indexes; explicit uniqueness and CHECK constraints.
Domain tables follow master spec section F, adding durable outbox, provider-call
attempts, spend reservations and disk reservations where required. PostgreSQL is
the sole authoritative store; do not substitute SQLite for concurrency evidence.
Wallet ledger and staff/financial audits are append-only with restricted DB privileges.
Financial history is not cascade-deleted when media/account deletion occurs.

One reviewed Alembic revision sequence, grouped by phase. Explicitly name constraints;
review generated SQL and validate upgrade/downgrade on a disposable PostgreSQL DB.
Use expand/migrate/contract for changes with existing data. Run one migration job
before application rollout, never from every worker. Back up before destructive
changes; financial rollback normally restores compatible code or uses a forward
fix, not deletion of ledger rows. Phase 1 adds revision 39bc6d102a49 for identity/auth;
Phase 2 adds revision dd9634e4866b for financial schemas; job schemas remain future work.

## Identity and API contract

Server-managed opaque sessions with only token hashes stored, rotation/revocation,
Argon2id passwords and expiring hashed single-use email/reset tokens. Staff RBAC
is checked in services; ownership is part of every resource query. Google uses
standard OIDC state/nonce/PKCE as applicable, issuer/audience/expiry validation and
verified ownership for linking. Missing configuration returns explicit disabled state.

Use `/api/v1`, typed request/response models, stable operation IDs, bounded cursor
pagination and UTC ISO timestamps. Generate OpenAPI from actual FastAPI routes,
snapshot it in CI and document disabled capabilities; no hand-authored pretend API.
System health paths follow master spec (`/health/live`, `/health/ready`). Readiness
checks dependencies without exposing secrets; docs restricted in production.

Proposed `application/problem+json` error (not an implemented response):

```json
{"type":"urn:zoclip:problem:insufficient-capacity","title":"Capacity unavailable","status":507,"code":"insufficient_capacity","detail":"Retry later.","instance":"/api/v1/uploads","request_id":"opaque-id"}
```

Validation adds bounded safe `errors` field entries; never echo secrets/paths.
Use 401 unauthenticated, 403 forbidden/CSRF, 404 hidden foreign resources,
409 conflicting state/idempotency payload, 412 stale revision, 422 invalid input,
429 throttled, 503 dependency/budget admission unavailable, 507 disk capacity.
Exact DTOs and codes become executable contracts in their implementation phase.
Mutations use scoped `Idempotency-Key` where replay matters; save payload hash and
result. Quotes are read-only, versioned, expiring and revalidated at reservation.
Clip edits require revision/If-Match checks. Progress reflects real milestones;
unknown queue position remains null.

Later frontend: prefer `app.<domain>` and `api.<domain>` under the same HTTPS site.
Use host-only API session cookie (`Secure`, `HttpOnly`, `SameSite=Lax`, path `/`,
no broad Domain attribute), credentialed fetch and exact allowed frontend origin.
Never wildcard credentialed CORS. CSRF token/header and Origin checks protect
mutations; OIDC callback validates its protocol state separately. Allow only needed
methods/headers, including CSRF, idempotency and revision headers. Development
localhost exceptions are explicit and rejected in production. Unrelated frontend
domains require a separately reviewed cookie/CSRF deployment decision; prefer a
same-site custom domain. v0 gets generated OpenAPI later and owns presentation,
not balances, payment verification or provider credentials.

## Money and spend state machines

Wallet has integer available A and reserved R, both >=0. Every mutation locks the
wallet, enforces unique `(scope,idempotency_key)`, inserts ledger deltas and updates
balances in one transaction. Reconciliation sums ledger deltas against materialized
balances and open reservations; discrepancies stop affected financial operations.

| Operation | Available delta | Reserved delta | Rule |
|---|---:|---:|---|
| GRANT | +n | 0 | verified payment or explicit audited grant |
| RESERVE | -n | +n | A >= n; unique reservation/job |
| SETTLE | 0 | -n | held reservation, deliverable verified, once |
| RELEASE | +n | -n | held reservation, final failure/cancel, once |
| REFUND of GRANT/reversal | -n | 0 | recover only unspent credits under policy |
| REFUND of SETTLE | +n | 0 | restore credits up to the original settled charge |
| ADMIN_ADJUST | signed n | 0 | RBAC, reason, nonnegative result |

Reservation: HELD -> SETTLED or RELEASED, never both. MVP whole-job charge only
on successful requested deliverable; no partial customer charges. Paid extra renders
have their own quote/reservation and capped exports. Phase 4 suggestions-only jobs
must remain SUGGESTIONS_READY without claiming rendered completion; settlement
awaits the explicitly agreed deliverable, and abandoned holds require timeout policy.

Job creation atomically commits reservation, job and outbox. Completion atomically
records verified outputs and settlement; failures atomically release. Files are
written privately to temporary paths, validated and atomically promoted before DB
commit; orphan cleanup handles file/DB crash gaps. Output uniqueness includes job,
clip and revision so duplicate workers cannot duplicate exports.

Before each paid request, atomically reserve conservative spend against job/user
and global daily/monthly counters, including other in-flight requests. Lock budget
rows in a consistent order; never check totals then increment outside a transaction.
Missing model/rates/budgets or unbounded response size blocks calls. Bound tokens,
duration, attempts and timeout; reconcile actual usage with estimates. Unknown
provider outcome retains exposure for reconciliation, not blind retry/release.
Use provider idempotency only when officially supported; local caching alone cannot
guarantee exactly-once remote billing after a crash. Failed-job costs count internally.
Daily/monthly accounting uses UTC, with PKR reporting separate from USD costs and
explicit exchange-rate assumptions. No profitability promise.

Order: CREATED -> PENDING -> PAID; unpaid paths may EXPIRE/FAIL/CANCEL. Verified
late payment enters reconciliation, never disappears or auto-grants an expired
offer without policy. PAID may enter REFUND_PENDING/REFUNDED/DISPUTED under verified
provider evidence. Verification checks authenticity, provider status, immutable
reference, amount, currency and price version. Unique provider event and order grant
constraints plus locked order/wallet make paid transition and grant atomic. Browser
redirects only display server status. Reversal with consumed credits freezes affected
access and records exposure; never silently overdraws. Adapter contract:
create_checkout, verify_notification, query_transaction, refund_if_supported.
Mock sandbox is dev/test only; live adapter remains disabled pending merchant docs.

## Media lifecycle and ingestion

Source: CREATED -> UPLOADING/IMPORTING -> VALIDATING -> READY.
Processing: CREDIT_RESERVED -> QUEUED -> EXTRACTING_AUDIO -> TRANSCRIBING ->
ANALYZING -> SUGGESTIONS_READY -> RENDER_QUEUED -> RENDERING -> COMPLETED.
Transient stages may RETRY then resume safe checkpoint; final FAILED/CANCELED
release holds. Central transition rules reject illegal state changes. Bounded
exponential backoff/jitter, heartbeat leases, dead-letter state and cancellation
checks precede expensive actions. No repeated transcription of unchanged content.
Cache keys include owner/source digest, model, settings and prompt version.

Stream bounded chunks to random private storage IDs, account duplicates/reordering,
validate checksums and atomically finalize; never trust filename, MIME or extension.
Probe with sandboxed ffprobe, capped metadata and deadlines. Import authorized direct
HTTPS media only, initially explicit host allowlist, port 443, no URL credentials.
Resolve and reject any unsafe IPv4/IPv6 address; connect to validated address while
preserving TLS hostname verification and revalidate every redirect/connection to
prevent DNS rebinding. Disable automatic unchecked redirects and environment proxies;
cap bytes, redirects and time. YouTube/platform pages return `unsupported_source`.

Deepgram gets extracted speech audio; Gemini gets bounded transcript text, not full
video. Validate structured candidates, word alignment, duration and duplicates.
Render selected intervals only at 720x1280 H.264/AAC, safe generated ASS captions,
bounded FFmpeg threads and sampled face-aware crop with center fallback. Multi-person
tracking and subjective Urdu/Unicode caption quality require real fixture review.
Edits are non-destructive revisions; unchanged audio/transcripts are reused.

Private filesystem storage interface supports a future S3/R2 adapter. Authenticated
streaming is initial download default; any expiring link binds object/revision and
checks revocation policy. Delete first revokes access/cancels jobs, then idempotently
removes files and metadata according to retention. Cleanup never deletes active work.

## Contabo admission and operations plan

Planning envelope for 8 GB: host/proxy 1 GB, PostgreSQL 1.5 GB, Redis 0.25 GB,
API 0.75 GB, AI worker 1 GB, render worker 2 GB, scheduler 0.25 GB, spare 1.25 GB.
These are provisional budgets, not measured RSS or final Compose limits. Start one
API process, one AI worker, one render worker, FFmpeg at two threads. Shared CPU and
memory caps cover extraction/probe/face detection too, not just final rendering.
Initial DB pool per process: size 2, max overflow 0; reconcile total connections with
PostgreSQL limit. Initial queue cap 10 pending processing jobs, one active processing
job and one upload/import per user; global two simultaneous ingestion sessions.
All are configurable and subject to measured adjustment.

4 GiB source and 120 minutes are upper admission limits, not capacity guarantees.
At least 20 GB free must remain after outstanding disk commitments. Under a DB lock,
reserve conservative additional source + duplicate finalization + audio + render
scratch + requested outputs; recheck actual filesystem free bytes at each stage.
Define reservation remaining bytes to avoid double-counting bytes already materialized.
Reject unknown/unbounded estimates or projected headroom breach with 507. Bound
retained aggregate media too. A 100 GB drive includes OS/images/DB/backups/logs, so
do not infer a guaranteed number of 4 GiB sources. Start a 40 GiB retained-media
ceiling, subject to actual filesystem size and headroom; lower limits win.

Proposed configurable retention defaults: incomplete uploads 24h; transient audio/
scratch delete immediately after terminal state (cleanup retry <=24h); originals,
transcripts and final clips 7 days. Originals must remain while editing is offered;
expiry ends editing and warns the user. These are engineering defaults pending
commercial/privacy approval, not published terms. Financial/audit retention and
backup expiry require legal policy; deletion must document delayed backup removal.

Nightly encrypted off-server PostgreSQL backup, essential config recovery, rotated
logs and restore drills are launch requirements; destination not selected. Local
media has no implied disaster recovery guarantee: backup/restore policy and any
off-server media cost need approval. Alert on disk, queues, worker heartbeat,
provider spend, payment anomalies and failure rates. UFW, TLS renewal, non-root
containers, dropped capabilities, restricted mounts and trusted proxy configuration
are Phase 7 deliverables. Benchmark 10/30/60/120-minute media before capacity claims.
