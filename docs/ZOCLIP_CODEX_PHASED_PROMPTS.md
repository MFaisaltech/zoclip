# ZoClip — Codex Production Backend Prompt Pack (v1.0)

## How to use these prompts

1. Start a **new GitHub repository** named `zoclip` or `zoclip-backend` and open that repo/workspace in Codex. Codex needs repository write access.
2. Copy `ZOCLIP_BACKEND_MASTER_SPEC.md` into the repository at `docs/ZOCLIP_BACKEND_MASTER_SPEC.md`. This is the authoritative product contract.
3. Send **Prompt 0** to Codex; review its output. Then send **Prompt 1**, wait for it to finish, inspect/test/commit, then continue **one phase per prompt**. Do not send all at once.
4. If Codex can't run Docker, integration tests, or reach a credentialed external API in its environment, instruct it to implement tests/mocks and report the **exact verification blocker**. Never let it claim unrun tests passed.
5. Do not paste real API keys, Google client secrets, server credentials, or payment merchant secrets into prompts. Codex must use environment placeholders; configure secrets in deployment yourself.
6. After each phase, save a git commit and a written handoff. Keep the next step blocked until required tests and migrations pass. Use Codex to fix test failures before moving forward.
7. Do **not** treat a successful demo video as production readiness: payments, race conditions, unsafe URLs, user isolation, backups, throttling and resource limits are separate gates.

### Standing rules for every Codex phase

All phases below inherit these instructions:

- Read `docs/ZOCLIP_BACKEND_MASTER_SPEC.md`, `AGENTS.md`, repository state, prior implementation and tests first. Preserve architecture and schemas unless explicit migration/version change justified.
- Make **real code edits**; do not stop at pseudocode/architecture or produce simulated success on production routes. Mocks only under explicit test/dev adapter.
- Implement exactly the requested phase and necessary shared refactors, not unrelated features.
- Use stable, maintained dependency versions compatible with Python 3.12, PostgreSQL, Redis/RQ, FFmpeg and Ubuntu 24.04. Check current provider docs before copying SDK snippets. Pin major versions and document them.
- Keep backend secure multi-tenant and designed for one 4-vCPU/8-GB host; no GPU, Kubernetes, expensive managed SaaS or automatic paid add-ons.
- Use idempotency keys, deterministic job state transitions, proper DB locking and migrations for financial/job changes. Do not expose secrets/PII in logs or API responses.
- Include unit/integration/security/regression tests for this phase, run them when possible, and report exact commands and results. Explain manual steps and blockers explicitly.
- Generate/update OpenAPI from actual routes and keep `docs/API_HANDOFF.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`, and `.env.example` current.
- Final response after each phase must give: implemented files/features, commands run and results, tests not run and why, migration notes, new env variables, security/cost implications, limitations, and suggested git commit message.
- **Never** award credits due to browser redirects, allow negative credits, expose another user's data, fetch URLs without SSRF protections, spend a paid API call without cost authorization, or pretend external merchant/provider credentials exist.

---

# PROMPT 0 — Repository audit and implementation blueprint (no big code yet)

> Paste this into Codex when the repository contains only the master specification or an empty scaffold.

```text
You are the principal backend engineer for ZoClip, a Pakistan-first paid AI video clipping SaaS. Read docs/ZOCLIP_BACKEND_MASTER_SPEC.md completely and treat it as the implementation contract.

Our existing server: Contabo Cloud VPS 4, Ubuntu 24.04, 4 vCPU, 8 GB RAM, 100 GB SSD, $13.20/mo. Stack: FastAPI, Python 3.12, PostgreSQL, SQLAlchemy 2, Alembic, Redis + RQ, Deepgram, Gemini, FFmpeg, Docker Compose. Input uploads and supported video URLs; max video 120 minutes. MVP auto moment selection, animated word-timed captions, smart 9:16 reframe, non-destructive edits, titles/hashtags. Authentication: email/password and Google login. Billing: Pakistan-first PKR prepaid credits/plans; live local gateway pending merchant selection.

TASK FOR THIS PHASE ONLY:
1. Audit this repository and the master spec. Do not implement product features yet.
2. Identify gaps, ambiguous requirements and specific operational risks on 4 vCPU/8 GB/100 GB.
3. Create AGENTS.md with the project's immutable engineering and security guardrails.
4. Create docs/ARCHITECTURE.md showing components, DB/queue boundaries, storage, auth, media states and money states.
5. Create docs/IMPLEMENTATION_STATUS.md with all phases and completion gates, docs/DECISIONS.md listing final defaults vs pending merchant/domain/price decisions, and a concise test matrix.
6. Propose module tree, dependency constraints, migration approach, structured error envelope and OpenAPI conventions. Choose safe defaults instead of inventing payment-provider details. Include disk-headroom policy and default worker concurrency.
7. Plan for a Next.js frontend to be generated later by Vercel v0; describe API/cookie/CORS needs. Frontend is NOT in scope.
8. Highlight the supported-URL policy: user-authorized direct HTTPS media URL now; other site providers only through compliant adapters; protect against SSRF.

Do not request real secrets. Do not falsely claim deployment or tests. Return a short handoff and exact next prompt phase.
```

**Gate 0:** architecture and status documents exist and agree with the master spec; no unsupported claims about universal URLs, free API quotas, or live Pakistani payment merchants.

---

# PROMPT 1 — Foundation, secure authentication and multi-tenancy

```text
Read the ZoClip master spec, AGENTS.md and all current repository files. IMPLEMENT PHASE 1 ONLY: a runnable FastAPI backend foundation plus production-oriented user/authentication system.

Deliver:
- Clean modular monolith; Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Redis and RQ infrastructure ready, Docker Compose for API/db/redis/worker (worker can have an empty task queue for now), dependency lock/constraints, structured logging, settings validation, liveness/readiness health endpoints.
- PostgreSQL migrations for users, oauth_identities, server sessions/refresh tokens, email verification/reset tokens, audit logs, and required indexes/uniqueness. No SQLite fallback in production.
- Secure email/password register, verification, login, logout, reset request/reset confirmation, GET /api/v1/me; password hashed with Argon2id, hashed single-use expiring reset tokens, email-provider adapter with development mailbox only. Prevent user enumeration and brute-force attacks.
- Google OIDC integration with standard library, state/nonce/PKCE where relevant, validated ID tokens, verified account linking. If Google client credentials absent, return explicit disabled/unconfigured rather than fake login.
- Use server-managed sessions, secure HttpOnly cookie options, CSRF defense for mutations, explicit permitted CORS origins, token rotation/revocation, user status checks and secure error responses.
- Add permission helpers that scope all resources by current authenticated user and fail 404/403 properly. Enforce role checks for admin APIs.
- .env.example with placeholders (never actual secrets), development vs production settings, no open DB/Redis ports to Internet in prod.
- Build tests: register/login/logout, password-reset single-use, expired tokens, OAuth invalid state, forged cookie/CSRF, login throttling, role checks, email verification and Alice/Bob isolation helper; migration up/down smoke.
- Produce docs/AUTH_HANDOFF.md and the actual OpenAPI schema. No frontend yet.

Run lints/type checks/tests/migration as available; fix failures, list blockers. Do not implement billing or real AI in this phase.
```

**Gate 1:** a real user can register, verify, log in and out; test users cannot gain each other's identity or admin role; disabled Google configuration fails cleanly.

---

# PROMPT 2 — Ledger, plans, credit quote and cost budget engine

```text
Read the master spec and Phase 1 code. IMPLEMENT PHASE 2 ONLY: ZoClip's atomic, auditable credit and financial-control foundation. All balances must be real PostgreSQL data; no fake UI state or Redis-only balances.

Deliver:
- Schema and migrations for wallets (available/reserved), append-only credit transactions, unique reservations, plans, versioned PKR price definitions, user entitlements, configured credits/grants, consumption rules, system/provider cost limits, and admin audit. Currency amounts are integer paisa; providers' USD costs use Decimal/fixed precision.
- One wallet per user. Implement GRANT, RESERVE, SETTLE, RELEASE, REFUND, ADMIN_ADJUST operations with strict transactional semantics and SELECT FOR UPDATE locks; reconcile helper and CHECK constraints prevent negative available/reserved. Never erase historical ledger entries. Unique operation/idempotency keys.
- POST /api/v1/jobs/quote (given source duration, feature choices, output count/edit limits), GET /api/v1/plans, GET /api/v1/me/credits, GET /api/v1/me/credit-transactions, GET /api/v1/me/entitlements. Quote is server-calculated and versioned. For launch prices/credits, keep admin-configurable placeholder plans clearly marked noncommercial/unapproved.
- Rules for max input 120 minutes, plan caps, per-user max concurrent jobs, daily/monthly usage, render/edit quotas. Include guarded first-time trials disabled by default pending anti-abuse controls.
- Internal USD estimate/budget gates before Deepgram/Gemini usage: configurable model rates and token assumptions, price-version and max-per-job allowance, per-user and global daily/monthly provider-cost budgets, circuit breakers, metrics. Safe fail closed if expected usage exceeds configured budget; never rotate keys to evade free quotas.
- Worker/job independent reservation contract to be consumed by next phases. API requests must be idempotent; duplicate quotes must not charge; duplicate reservation/settlement/release must not change credits twice.
- Tests simulating 10 duplicate requests, concurrent reservations from a wallet with insufficient funds, refunds and out-of-order settlement, negative balance attempts, double-grant prevention, and accounting reconciliation.
- docs/CREDITS_AND_MARGIN.md documenting cost assumptions vs measured costs and why profit cannot be guaranteed.

Do not integrate live payments yet and do not claim the plans' prices are economically validated. No provider API calls in this phase.
```

**Gate 2:** wallet cannot overdraw even with parallel jobs and retries; test/admin seeded credit balance is auditable; quote, reservation and settlement reconcile exactly.

---

# PROMPT 3 — Secure uploads, supported links, media validation and queue

```text
Read the master spec and phases 1–2. IMPLEMENT PHASE 3 ONLY: secure video source ingestion and durable background job state machine.

Deliver:
- Private local filesystem storage abstraction; UUID-based object IDs, owner restrictions, directories not web-accessible, retention/cleanup and disk free-space guard. Future S3/R2 adapter interface, not required today.
- Resumable, streamed chunk uploads: POST /api/v1/uploads, PUT /uploads/{id}/parts/{part_number}, POST /uploads/{id}/complete, DELETE /uploads/{id}. Atomic finalize and integrity checks, 4 GB configurable max, resource reservations, orphaned upload cleanup. Never buffer whole uploads in memory.
- Import POST /api/v1/videos/import-url: only explicitly allowed supported direct HTTPS video URLs at first; consent/rights attestation; DNS and every redirect verified against internal/private/metadata IP ranges; URL scheme/port restrictions, size/time caps, MIME and magic validation, safe streaming. Unsupported YouTube/platform URL must return documented `unsupported_source` until legal/provider-compliant adapter exists; no stealth scraping or bypass.
- ffprobe validation of actual playable media, duration <=120 minutes, audio/video streams, codec/size constraints, timeouts, no shell interpolation. Reject malicious and invalid inputs safely, never create public files.
- DB migrations for source_videos, projects, upload_sessions, job states/events, storage objects; secure GET/LIST/DELETE; enforce user entitlements and limit active upload/import jobs.
- RQ queues separating AI and render; at-most-one active render by default, bounded AI workers, valid state transitions, per-stage idempotent checkpoints, cancellation status, event logs, heartbeat/recovery, retries, redaction. No real AI charges in this phase.
- Quote/reserve credits before allowing a billable processing job to enter the queue; ingestion preflight itself must not consume heavy resources without account limits. Wire a deterministic mock processing worker only for tests, clearly not a real video engine.
- Tests: chunk reordering/duplication, partial uploads, >size, >duration, malformed video, SSRF localhost and rebinding/redirect attempts, file path traversal, private-media IDOR, full disk condition, worker retry/recovery, insufficient credit rejection and teardown cleanup.
- README instructions, generated API schema, fixtures with small actual sample videos if license-safe.

Provide exact way to run `docker compose` locally and verify API with curl. Do not implement real AI yet.
```

**Gate 3:** a user can upload a real playable media file in chunks, submit a supported direct media URL, create a job, see status, and cannot access another user’s media. Unsupported links have clear errors.

---

# PROMPT 4 — Real Deepgram and Gemini processing, clip suggestions

```text
Read the master spec and all completed phases. IMPLEMENT PHASE 4 ONLY: the actual transcript-and-AI highlight discovery stage with real provider adapters, cost controls, and deterministic tests.

Deliver:
- FFmpeg extracts appropriate audio from validated uploaded video without full-video re-encoding; streaming/temporary files with time/CPU/disk guard.
- Deepgram prerecorded integration behind an interface; one transcription per unchanged source/audio digest; word start/end/confidence/punctuation plus optional utterances/speaker metadata, provider model and usage stored, failures and 429/5xx handled with bounded retry/backoff; track billable minutes and estimate USD charges. API key env-only.
- Gemini integration through current official SDK/API using configured accessible model ID. Send transcript and segment context, NOT full video by default. Produce structured JSON via schema with moment start_sec, end_sec, title, hook, reason, score, keywords/hashtags. Validate with Pydantic, ensure timestamps within 0..duration, maximum number, word-aligned boundaries, no overlapping duplicates, clip-length ranges and reasonable fallback on empty/invalid outputs. Never send output straight to FFmpeg commands without validation.
- Chunk long transcripts where needed; cache exact transcript+model+prompt version results, re-use under repeated jobs instead of repeating billable requests. Limit prompt size, tokens, candidate count and retries. Log provider usage and charges without exposing transcript in public logs.
- Before every external paid request check authorization, credit reservation and configured budget, plus provider rate limit; after completion store cost and capacity metrics. If request cannot proceed, fail with meaningful state and correct credit release; never assume free quotas.
- Return real suggestions and transcript via owner-scoped GET /videos/{id}/transcript and /videos/{id}/suggestions. Render is not required in this phase; suggestions state must be accurately labeled.
- Unit tests against mocked provider payloads, bad timestamps, giant output, timeout/429/500, repeated jobs, transcript chunking and schema violations. Add optional manually invoked real-provider smoke test that never runs automatically/without secrets.
- Docs: exact Deepgram and Gemini models/configuration, possible paid features, model price assumptions, data processing/privacy disclosure, sample suggestions response, API update.

Mark incomplete rendering distinctly. Do not pretend a generated clip exists yet.
```

**Gate 4:** one actual audio file can be transcribed and yield validated, useful timestamped suggestions under real configured credentials, and the test suite works without them.

---

# PROMPT 5 — FFmpeg output, captions, smart reframing and editor API

```text
Read the master spec and all prior phases. IMPLEMENT PHASE 5 ONLY: real clip creation and minimal non-destructive editing, with quality/speed safeguards suitable for a CPU-only 4-vCPU host.

Deliver:
- Render suggested source sections (not entire full source) using FFmpeg, H.264 + AAC MP4 in 9:16 720x1280 default. Validate metadata/duration/frame dimensions and playable output with ffprobe; ensure source audio and caption synchronization.
- Word-timed captions with 2–3 attractive but CPU-feasible caption presets, correct line breaks/safe zones, escaped special characters/Unicode, measurable subtitle timing and deterministic outputs. Use safe generated ASS files and subprocess arg lists with shell=False; don't allow arbitrary FFmpeg filter strings.
- Smart face-aware reframe: sampled CPU OpenCV face detection, weighted focus by detected speaker/face where feasible, smooth temporal transitions and fall back to centered composition when tracking fails. Cap analysis density and time. Be candid about multi-speaker limitations; no fake AI face-tracking labels.
- Support clip detail, revise start/end within original source and plan constraints, edit caption text/styles, editable title/hashtags, manual crop focal position, revision locking, and rerender single changed clip without repeating Deepgram/Gemini. Enforce render/edition quotas and additional quote/reservation when plan limits exceeded.
- Private output access with authenticated download or time-limited signed link; never serve `/media` as public. Persist outputs, render stats and revision relationships; secure delete/TTL cleanup.
- Robust concurrency: single render worker by default, bounded ffmpeg threads, subprocess deadlines/resource caps, cancellation and partial cleanup, adequate disk free-space; separate AI queue from rendering.
- Wire complete job completion to wallet settlement exactly once; worker errors release reservation exactly once; avoid charging for bad output, never double-settle on retries.
- Tests: representative local sample video -> playable vertical captioned MP4, captions with special characters, no detected face fallback, invalid clips and zero-duration ranges, concurrent render throttle, canceled/failing FFmpeg rollback, second user cannot download, edited clip keeps original source transcript cached.
- Benchmark scripts/docs for 10/30/60/120-min sources (only run heavier tests when opted in), reporting CPU/RAM/disk/queue/API costs/clip render time.

Do not build B-roll or expensive external vision APIs. Output a real clip demo path in local test environment, not an invented URL.
```

**Gate 5:** full authenticated file upload -> transcription -> selection -> actual MP4 clips works end-to-end; editing and re-rendering a single clip works; tests verify quality and finances.

---

# PROMPT 6 — Pakistan local payment integration architecture and commercial plans

```text
Read the master spec and existing wallet/job engine. IMPLEMENT PHASE 6 ONLY: real payment-domain design and verifiable sandbox order-credit workflow suitable for Pakistan. Never claim a live gateway until a merchant is approved and real docs/credentials are supplied privately.

Deliver:
- Versioned Free/Creator/Pro/Business plan definitions plus optional pay-as-you-go packs, access limits, PKR price integers in paisa and corresponding credit quantity. All launch prices are placeholders pending measured unit economics and business approval. Represent paid plan as prepaid 30-day entitlement unless chosen provider genuinely supports and merchant enables recurring billing; do not silently auto-renew.
- DB migrations for billing_orders, payment_attempts/events, refunds/chargebacks, immutable gateway references, entitlement grants and rate version. Currency amount stored in integer smallest units, provider fees and USD AI costs tracked separately.
- PAYMENT PROVIDER INTERFACE: create_checkout, verify_notification, query_transaction, refund_if_supported. Build `MockSandboxProvider` for tests/dev, disabled for public production payment. Integrate a real named Pakistan gateway only IF its current official merchant docs and supported callback verification can be verified; otherwise leave a clearly disabled adapter and merchant onboarding checklist, not a pretend successful charge.
- POST /billing/orders, GET /billing/orders/{id}, GET /billing/history, secure POST /billing/webhooks/{provider}, plans endpoints. Server creates exact expected amount/currency/version, validates callback authenticity, gateway status and order ownership/reference/amount/currency before granting credits. Return URL is only a user-facing status page, never credit-authoritative.
- Absolute idempotence under duplicate/out-of-order webhook, replay, concurrent callbacks, delayed payment, partial failure between payment and grant; perform atomic paid-order transition and credit grant in one DB transaction with unique constraints.
- Mock reversal/refund/chargeback paths and reconciliation process; if credits are spent and gateway reverses funds, flag account/risk exposure rather than allowing negative wallet balance without explicit policy.
- Admin/audit support for verifying orders and gateway reconciliation, but no unauthorized manual granting. Refund and manual adjustment actions require role and reason.
- Tests: fabricated success redirect grants 0, invalid signature grants 0, wrong amount/currency/reference grants 0, duplicate valid callback grants exactly once, delayed callback, concurrent callbacks, ledger consistency, expired orders and no hosted-secret leakage.
- docs/PAKISTAN_PAYMENTS.md describing merchant signup requirements, test/live switches, webhook configuration, gateway fees as TBD unless verified, manual sandbox steps and honest status of live capability.

IMPORTANT: No final retail prices should be presented as profitable until per-hour AI/render/storage/gateway costs are benchmarked and margins approved. Do not assume JazzCash, Easypaisa or any provider has approved us.
```

**Gate 6:** a sandbox **verified** payment credits exactly once, a spoofed payment credits zero; no accidental live charging or bogus subscriptions.

---

# PROMPT 7 — Production security, load limits, monitoring and deployment

```text
Read the master spec, the full codebase and implementation status. IMPLEMENT PHASE 7 ONLY: make the system operationally safe on our existing Contabo Ubuntu 24.04 server (4 vCPU/8 GB/100 GB SSD), without buying a GPU or new hosting.

Deliver:
- Production Docker Compose with API, Postgres, Redis, AI worker(s), one FFmpeg render worker, scheduler/cleanup service and Nginx. No published DB/Redis ports. HTTPS instructions, security headers, allowed domains/CORS/CSRF/session cookie configuration, firewalls, healthchecks, restart rules, migrations, log redaction, non-root services and safe file permissions.
- Resource budgets and admission control: worker concurrency defaults, queue-depth caps, DB pool limits, `ffmpeg` timeouts and thread cap, API rate-limit/rate-budget gates, 20-GB disk headroom, 4-GB file cap and 120-min duration cap. 100-GB SSD has to serve system, DB, raw media, clips and scratch; document practical supported working set.
- Retention/cleanup, expiration, cancellation and deleted-account data handling; backup encrypted Postgres off the server plus restore drill; log rotation; operational monitoring and alerts for high disk, worker dead, unusual payment/refund pattern, API cost spikes, 429s and job failure rates.
- Cost dashboard/endpoint/report showing actual provider minutes/tokens, estimated USD API charge, VPS budget allocation, failure costs, media storage and earnings in PKR; flag margin below admin target. Payments/provider rates are configured data, not hardcoded unverifiable current claims.
- Security tests for login rate limiting/CSRF, SSRF redirects, path traversal, IDOR, malicious media, concurrent wallet spend, webhook replay, duplicate workers, admin role escalation. Run stress tests against disposable data and safe mock providers; do not surprise real Gemini/Deepgram with load.
- Deployment and rollback scripts plus docs/DEPLOY_CONTABO.md with exact copyable commands and prerequisites, DNS/email/OAuth callbacks, secret injection, DB backups/restore, worker count change, domain TLS renewal, smoke tests and rollback.
- Failure drills: simulate DB outage, Redis outage, worker crash, Deepgram 429, Gemini timeout, insufficient disk, FFmpeg failure. Show credits recover, no charge duplicates, and user sees honest status.

Be transparent: this phase is not fully deploy-verified if you have no VPS access, and don't request VPS passwords in chat. Provide manual rollout checklist.
```

**Gate 7:** deployment scripts, safety checks, end-to-end tests and cost monitoring are ready; explicitly identify real-world items still requiring credentials/manual server execution.

---

# PROMPT 8 — Vercel v0 frontend handoff, final audit and release gate

```text
Read the master spec and ALL implemented ZoClip backend code. IMPLEMENT PHASE 8 ONLY: validate backend completeness and produce an exact Next.js/v0 frontend integration package. Do not build the frontend.

Deliver:
- Generate OpenAPI JSON/YAML from running FastAPI implementation, and run schema validation. Do not handwrite fictitious endpoints; include auth, upload chunks, supported URLs, job quote/start/progress, suggested clips, editor revisions, downloads, plans, credits, orders, payment status and admin routes.
- `docs/API_HANDOFF_FOR_V0.md`: page-by-page frontend requirements and real endpoints, request/response JSON examples generated from actual Pydantic models, state diagrams, auth cookies/CSRF/CORS, upload UX, job progress polling, stale revision conflicts, server errors, and logout; mark disabled Google and gateway configuration states accurately.
- `docs/V0_FRONTEND_MASTER_PROMPT.md`: a paste-ready, visually ambitious Vercel v0 prompt to create a cohesive responsive Next.js/TypeScript frontend with landing, pricing, signup/login, upload dashboard, processing progress, suggestion selection, clip preview/editor, download library, credits/top-ups/billing, profile and staff screens. Use the backend OpenAPI contract only; no fake credits, pseudo-payment-success, or fabricated results in production mode. Mock API is allowed only behind a development flag and clearly labeled.
- Export JSON samples for all core DTOs and an optional typed TypeScript API client generation recipe, with API errors and backend-defined enum states.
- Full status audit: each MVP requirement PASS/PARTIAL/FAIL + actual evidence (tests, files, endpoints, media fixtures). Run automated tests and safe load/security smoke tests where possible. Identify actual unimplemented features, model keys/Google OAuth/email/merchant requirements, QA benchmarks, legal/copy placeholders and prelaunch obligations.
- Final 4-vCPU/8-GB/100-GB capacity notes and measured numbers where available (never invent benchmark results). Provide a small-step release plan and rollback strategy.

Do not declare production-ready unless every mandatory gate is verified. Return a short, honest summary and the exact files to give to v0.
```

**Gate 8:** v0 can build a frontend against the real documented API, and a single reviewer can tell exactly what is implemented, tested, configured, and still blocked.

---

## Quality-check prompt (use after **each** phase if Codex says 'done')

```text
Act as an independent skeptical reviewer of your last ZoClip phase. Compare it with docs/ZOCLIP_BACKEND_MASTER_SPEC.md and the phase acceptance gate. Do not write a marketing summary.

1. List every required feature and mark VERIFIED / IMPLEMENTED-NOT-TESTED / MISSING, with file paths, methods and test names.
2. Run available format/lint/type/test/migration commands and print precise outcomes; do not invent success.
3. Try to break multi-tenancy, auth/CSRF, wallet concurrency/idempotency, billing callbacks, upload URL/SSRF boundaries, disk guards and retries as relevant to this phase.
4. Implement fixes for real problems you discover, add regression tests and rerun.
5. Show any mock-only path that a production route accidentally uses, and fail deployment if it can grant credits or output fake clips.
6. Update docs/IMPLEMENTATION_STATUS.md and give the next phase's real blockers, not assumptions.
```

## Integration discipline for v0 later

- Codex owns backend contracts; v0 owns the Next.js presentation; Codex finally integrates the two in the **same** repository or versioned API contract.
- v0 must not implement its own credits/account database, process payments from the client, or put Gemini/Deepgram keys into client bundles.
- Admin and customer views must rely on authorization enforced by FastAPI, not merely hidden buttons.
- Freeze versioned `/api/v1` response shapes before launching v0 generation; regenerate client types from OpenAPI when changed.

## How to interpret final readiness

**Prototype ready:** a valid private video becomes real short clips using configured Gemini/Deepgram, with tested account and credit flow.  
**Paid beta ready:** merchant sandbox verified, real privacy/security practices, limits, monitoring, recovery, legal policies, and manual real-provider checks done.  
**Public paid production ready:** approved merchant integration is verified end-to-end in live environment, backups restored successfully, abuse/rate/resource guardrails and cost-margin numbers validated, and no critical security failures.
