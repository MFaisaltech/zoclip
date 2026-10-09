# ZoClip engineering guardrails

## Scope and authority
Read `docs/ZOCLIP_BACKEND_MASTER_SPEC.md` completely, the requested prompt in
`docs/ZOCLIP_CODEX_PHASED_PROMPTS.md`, these rules and current implementation status
before changes. The user's requested phase controls scope; documents describing
future phases are not authorization to implement them. Preserve existing work.
Phase 0 is documentation only. Do not claim an application exists yet.

## Required architecture
- Python 3.12, FastAPI, Pydantic 2, synchronous SQLAlchemy 2 sessions, Alembic,
  PostgreSQL, Redis/RQ, FFmpeg/ffprobe; modular monolith on Ubuntu 24.04.
- PostgreSQL is authoritative for identity, money, job state and budgets. Redis
  is transport/cache, never the authoritative ledger. Sessions are per request/task.
- One render worker and one AI worker initially. Increase AI workers to two only
  after measurements. No GPU, Kubernetes or microservices required.
- Stream uploads; enforce 120 minutes, 4 GiB configured cap, at least 20 GB disk
  headroom and atomic capacity reservations for source, scratch and outputs.

## Security and privacy
- No live secrets in repository, fixtures, logs or chat. Use placeholders and
  validated configuration; production rejects placeholder secrets and mock payment mode.
- Scope every resource operation to its owner; staff access requires server RBAC
  and immutable audit events. Private media never gets a public static directory.
- Use audited Argon2id/session/OIDC libraries, hashed single-use tokens, secure
  HttpOnly cookies, CSRF checks, explicit CORS origins and rate limits. Google
  login stays disabled until configured and verified; no unsafe email linking.
- Support authorized direct HTTPS media only through the SSRF-safe importer.
  Validate DNS, connected IP and every redirect; block private/reserved/metadata
  destinations, unsafe protocols, credentials and unapproved ports. No scraping,
  DRM bypass or universal YouTube download claims.
- Constrain media subprocesses: argument arrays, shell=False, deadlines, resource
  limits, validated streams and escaped captions. Never accept user filter commands.
- Minimize/redact PII; disclose Deepgram audio and Gemini transcript processing.
  Retention, deletion, backups and off-server restore verification are mandatory.

## Financial and job invariants
- Integer credits and integer PKR paisa; Decimal/fixed precision USD costs.
  No floating point financial arithmetic; prices/models/rates are versioned data.
- Every balance mutation locks its PostgreSQL wallet and writes an append-only
  ledger in the same transaction. CHECK constraints prevent negative balances.
- GRANT, RESERVE, SETTLE, RELEASE, REFUND and audited ADMIN_ADJUST are idempotent.
  Expiry is disabled until disclosed policy exists. Reserve before enqueue; settle
  once for a successful deliverable; release once on final failure/cancellation.
- Enforce unique operation keys, payment event IDs and reservation/job links.
  Reject reuse of an idempotency key with a different request payload.
- Dispatch via durable PostgreSQL outbox; queue redelivery must be safe. Checkpoint
  provider responses and outputs. Never blindly retry an uncertain paid request.
- Atomically reserve estimated spend against job, user, daily and monthly limits
  before each paid call; include in-flight exposure and retry costs. Missing rates
  or budgets disable paid work. Failed jobs' sunk costs remain recorded.
- Only authenticated provider evidence with matching order/reference/amount/currency
  may atomically mark paid and grant credits. Browser redirects grant nothing.
  No invented gateway endpoints/signatures/fees or unapproved recurring billing.
- Mock providers are explicit test/dev adapters only; no production fake outputs,
  credits or payment success. Refunds never silently create negative wallets.

## Delivery discipline
Implement one requested phase. Verify current official provider documentation when
implementing integrations; pin reviewed compatible dependencies and lock versions.
Use actual PostgreSQL concurrency tests, disposable Redis, mocked paid providers
and real small FFmpeg fixtures as appropriate. Do not spend on real APIs in tests
without explicit opt-in. Never fabricate tests, benchmarks, migrations or deployment.
Update decisions/status and actual OpenAPI/API handoff as routes are implemented.
Report files, commands/results, unrun checks, blockers, migrations, configuration
changes and next phase. Never declare production readiness without acceptance evidence.
