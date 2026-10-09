# ZoClip — Backend Master Specification (v1.0)

**Status:** implementation contract for Codex, not a claim that software already exists.  
**Target:** Pakistan-first, commercial, multi-tenant AI podcast/long-form video-to-short-clips SaaS.  
**Version-1 input:** uploaded file **and** supported video URL.  
**MVP output:** AI moment detection, word-timed animated captions, 9:16 smart reframe, non-destructive clip editor, AI title/description/hashtags.  
**Maximum source duration:** 120 minutes, subject to file-size, disk, and plan quotas.  
**Infrastructure:** one Contabo VPS, Ubuntu 24.04, **4 vCPU / 8 GB RAM / 100 GB SSD**, Germany, **$13.20/month** already rented. No GPU required for initial launch.  
**AI services:** Deepgram prerecorded speech-to-text; Google Gemini for text-based clip discovery and metadata; FFmpeg/ffprobe for local media transforms.

## A. Product constraints and non-negotiables

1. Real, working backend — not generated UI, pretend features, hardcoded mock balances, or stubbed payment-success paths.
2. Zero live third-party credentials in source, prompts, fixtures, logs, tests or screenshots. Provide `.env.example` only; fail closed when required keys are absent.
3. User data and files are isolated on every read/write/download; admin capabilities require server-side RBAC and separate audit logs.
4. **Money never relies on the browser.** Payment verification, credit grants and reservations, entitlement checks, and refunds happen on server within database transactions.
5. **No assumption of guaranteed profitability.** Every external API call and render job is guarded by per-job customer credit balance, maximum spend settings and operational budgets. Hard-stop or fail safely when budget/quotas run out.
6. Source videos, transcripts, and clips are private by default, with expiring authorized download links or authenticated streaming.
7. Each phase must leave the repo runnable and tested. Never claim a feature works without meaningful verification. Clearly mark remaining blockers, especially real payment onboarding, emails/OAuth credentials, and load testing.
8. Implement the smallest modular monolith compatible with a single 8-GB host. Avoid Kubernetes/microservices/Elasticsearch/GPU dependencies.
9. Do not bypass content-site protections, DRM, account permissions or provider ToS to ingest video. Support uploaded media and **supported** URLs; specifically identify unsupported URLs with a clear API error. YouTube and other platforms require a permitted ingestion approach and a product/legal decision — do not silently promise universal URL downloading.
10. Avoid sending customer media to providers other than the disclosed subprocessors, and define retention and deletion flows.

## B. Technology decisions

- **Python 3.12** (Ubuntu 24.04-friendly), **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.x**, **Alembic**, PostgreSQL (single source of truth), **Redis + RQ** for separate `ai` and `render` queues, **FFmpeg/ffprobe** binaries, **httpx**/supported vendor SDKs for AI.
- Prefer synchronous SQLAlchemy sessions and short DB transactions in RQ workers; keep DB session per request/task. Do not share transaction/session across threads/processes. FastAPI can use ordinary sync database endpoints where appropriate.
- **Authentication:** audited libraries (Argon2id hashing, standard auth/OIDC library such as Authlib). Server-managed, HttpOnly, Secure, SameSite cookies, rotation/revocation of sessions; protect state-changing endpoints from CSRF and rate-limit account endpoints. Document cookie/CORS behavior for `app.zoclip...` and `api.zoclip...` deployments. No DIY cryptography.
- **Google login:** standards-based OAuth/OIDC using state, nonce and PKCE where applicable; accept only validated Google ID token/aud/iss/exp; safely link an email/password account only with proven ownership and verified email. Treat social login as disabled until valid configuration is supplied.
- **Storage:** private local filesystem mounted in Docker, organized by internal random IDs, not user file names; remote object-storage abstraction for future R2/S3; metadata in PostgreSQL. Expiring read access; retention cleanup.
- **Deployment:** Docker Compose, Nginx reverse proxy, HTTPS via Let's Encrypt or equivalent, Docker persistent volumes, systemd/Compose auto-restart, UFW, health checks, backup/restore runbook. PostgreSQL and Redis **not public**.
- **Testing:** pytest, factory fixtures, disposable DB and Redis in CI, mocked AI/payment providers, integration tests with actual FFmpeg for fixtures, type/lint, migrations, API contract snapshots.
- Never bake provider rates/models as immutable code constants. Make model IDs, token budgets and per-minute cost estimates configurable.

## C. Workload/capacity assumptions

- 4 vCPU/8 GB/100 GB is MVP hardware, not a guarantee of a 120-minute video's processing speed or 100 concurrent rendering jobs.
- Defaults: **one** FFmpeg render worker; **one or two** I/O-oriented AI workers after measurement; bounded API concurrency/rate limit; reserved disk headroom at least **20 GB**; one active render job initially.
- **120-minute** duration cap; initial configurable file cap **4 GB**, subject to adequate free disk and measured safety; auto-reject unsupported codecs, unexpected dimensions and high resource demand. Start with default processed output e.g. 720x1280 H.264/AAC and tune CPU presets experimentally.
- Resumable/chunked uploads must stream to disk, not buffer multi-GB files in RAM. Store only a bounded number of source files simultaneously. Estimate scratch disk before accepting work, and reject with 507/insufficient_capacity-style application error if insufficient space.
- Keep the source in a private retained location while editable, delete transient work on job completion/failure, and enforce explicit default TTLs for originals, intermediate audio, and final clips. TTLs configurable per plan.
- Do **not** re-encode entire 120-minute source to select moments. Extract/stream only the required audio for transcription, then render selected intervals.
- Benchmark with representative 10-, 30-, 60- and 120-minute files. Measure upload, transcoding, Deepgram wait, Gemini wait, queue wait, per-clip render, final job duration, peak RAM/CPU/disk, $ cost and error rate.

## D. User-facing flows

### D1. Account and trial
1. Sign up with email/password; verify email; login/logout; reset password; optional Google sign-in; view own profile.
2. New account receives **configurable small one-time trial allotment only if abuse controls are enabled** (email verification, rate limits, device/IP heuristic, abuse admin audit). Trial disabled by configuration by default in deployment until verified.
3. Account can view plan, credit grants/holds/charges, costs expressed in credits, history, and limits.

### D2. File upload / supported link
1. Authenticated user begins resumable upload (or submits supported HTTPS media URL they are authorized to process). Enforce plan, ownership attestation, content size, duration, concurrent job, disk and cost prechecks.
2. Streaming upload in chunks with server-side validation, size accounting, expiration and integrity checks; never trust extension/Content-Type alone. Use ffprobe in constrained subprocess with timeouts.
3. URLs: forbid SSRF; validate DNS and all redirects, block localhost and public-to-private redirects, cloud metadata endpoints, internal networks, unsafe protocols; cap downloads/time; reject unsupported link providers. No arbitrary `file://`/`ftp://`, credentials in URL, or shell invocation.
4. A `video` or `project` is created with secure lifecycle states and user-scoped metadata.

### D3. AI generate clips
1. On user submission, compute **deterministic credit charge based on source seconds, plan rules, requested features and allowable maximum exports**; show price via quote endpoint; **reserve** full credits once in a locked DB transaction before enqueueing.
2. `ffprobe` inspects track metadata. Fast audio extraction with FFmpeg, avoiding full-video re-encoding. Submit audio to Deepgram once; cache transcript + word start/end/confidence + optional utterances/speakers.
3. Gemini gets transcript/segments (chunk if necessary), instructions to find interesting non-overlapping clips, hook, reasons and scores. Ask for structured JSON and validate with Pydantic; clamp to source duration; align actual clip boundaries to word timestamps; reject invented/out-of-range/near-duplicate moments. Titles/hashtags grounded in transcript.
4. Saved moments available for editing before rendering or automatically rendered depending on explicit job config. Controlled render count prevents unlimited free re-encodes.
5. Render each selected section as 9:16 clips with captions. Smart reframe uses sampled face/subject positions (CPU-supported) plus smooth cropping; fallback to center crop when no face or tracking is unavailable. Document limitations, including multi-speaker scenes.
6. Support non-destructive editor model: change start/end timestamps, text/caption words/styles/position, crop positions and re-render one clip with revision/version. Do not re-transcribe/re-LLM call unless necessary. Enforce per-plan export quota and quote any paid extra renders.
7. Persist outputs, processing logs without secrets/PII, token usage and estimate/actual cost; settle credits once upon success. If a job fails, release reserved credits (or implement explicit user-accepted partial-charge rules; for MVP charge **only on successful deliverable** and manage partial sunk provider costs internally).
8. Support retryable infrastructure/API failures with exponential backoff plus jitter, dead-letter/final failure state, cancellation before expensive stages where feasible; never duplicate billing or export records.

### D4. Billing
1. Price list in **PKR**; amounts stored as **integer paisa** (or gateway-required smallest unit) and round only for display. Distinguish credits from currency; no floating point money.
2. Free trial, Creator, Pro, Business plan catalog and top-up packs, with server-configured quotas and explicit limits. Product prices and credits **not yet approved**; admin-configurable plans and versioned price definitions.
3. Phase-one billing model: **prepaid packs or 30-day access with included credits**. **Do not silently promise automatic recurring subscription billing** before the chosen Pakistani gateway confirms recurring tokenized payments are supported and merchant approval obtained.
4. Local payments: gateway adapter with sandbox/mock provider + an integration interface for approved Pakistan merchant provider (e.g., JazzCash merchant gateway / suitable licensed provider, subject to onboarding and current docs). **Never invent live API endpoints, signing algorithms, webhook shape, fees, account availability or merchant approval.**
5. Payment creation generates an immutable internal order (user, price version, amount, currency, expected credits, expiry) and an external gateway reference. Only verified signed callbacks or independently verified provider queries can move an order into `paid` and grant credits. Browser success redirects do not count. Enforce event and order idempotency.
6. Refunds/chargebacks require reversing granted credits where feasible, holding access if funds reversed and credits already consumed, and financial audit logs; never allow silent negative balances.

## E. Credit and cost-control invariants

- Database state is authoritative: **wallet** available/reserved, immutable **wallet_transactions**, uniquely identified **credit_reservations**, idempotency keys and constraints. Prefer a transparent accounting design with reconcile checks; each mutation is a transaction under `SELECT FOR UPDATE`/equivalent locking.
- Operations: `GRANT`, `RESERVE`, `SETTLE`, `RELEASE`, `REFUND`, `EXPIRE` (if a disclosed expiry policy is added), `ADMIN_ADJUST` (with audited reason and role).
- A reservation moves available -> reserved atomically; if unavailable, reject before enqueue. `SETTLE` debits only from reserved once; `RELEASE` returns unspent reserved credits exactly once; no negative available/reserved ever.
- Repeated client requests, webhook retries, worker crashes, duplicated job delivery, and concurrent purchases/renders must **not** duplicate credits or charges. Unique indexes on `(scope, idempotency_key)`, `(provider, external_event_id)`, and reservation/job linkage where appropriate.
- Source-minute pricing example: credits can represent minutes, but value must be **configurable**, not immutable. Charge quote consistent with reserve/settle; cap outputs and re-renders; no free unlimited retries for customer-requested edits.
- Profit guardrails: admin settings for per-job maximum estimated provider spend (USD Decimal), daily/monthly API budget caps, per-user quota, maximum job size, queue depth, per-model token limits, hard timeout and source-size limits. Estimate before provider call and record actual token/minute billing metadata; **no promise of guaranteed profit**. Temporarily disable new jobs when budgets exceed thresholds. Track API charges, compute usage cost per finished job and gross margin reports.
- Free-tier external API quotas are **not** reliable economic foundations. Use actual paid provider rates for commercial pricing, with promo/free credits treated only as temporary savings.

## F. Data model — minimum

Use UUID primary keys; `created_at/updated_at` UTC; FK indexes; soft delete only where appropriate; delete files appropriately.

| Table | Core fields / responsibilities |
|---|---|
| `users` | email (normalized unique), password hash nullable for OAuth, verified, status, role, timestamps |
| `oauth_identities` | provider + subject unique, verified claims, user FK; safe linking |
| `sessions` | hashed refresh/session token, expiry, revocation, user/device metadata |
| `password_reset_tokens`, `email_verification_tokens` | hash, single-use, expiry; no plaintext stored |
| `plans`, `plan_price_versions`, `user_entitlements` | PKR price, billing type, quotas, validity, current limits |
| `wallets`, `wallet_transactions`, `credit_reservations` | integer credits, immutable ledger, idempotency, account balance invariants |
| `billing_orders`, `payment_events`, `refunds` | amount integer paisa, state machine, gateway reference, signed/raw hash and unique event ID, no secrets |
| `projects`, `source_videos`, `upload_sessions`, `upload_parts` | user, source, duration, file path/storage ID, checksums, limits, states |
| `transcripts`, `transcript_words` or transcript JSON | Deepgram model, word-level timing, confidence, language and processing status |
| `clip_suggestions`, `clips`, `clip_revisions`, `render_outputs` | source timestamps, confidence, metadata, caption edits, crop metadata, output, version |
| `processing_jobs`, `job_events`, `provider_usage` | unique job id and step, retries, cost metrics, state and queue, failures |
| `admin_audit_logs`, `system_limits`, `rate_limit_events` | immutable staff actions, budget policy, abuse controls |

Avoid exposing filesystem paths, provider secrets, user payment tokens or private storage object names in public schemas.

## G. Minimal REST API contract (`/api/v1`)

All endpoints typed via Pydantic, auth enforced, RFC7807-like documented errors, pagination, stable schema generation. OpenAPI is a required deliverable and should match code.

**Auth:**
- `POST /auth/register`, `POST /auth/verify-email`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/password/forgot`, `POST /auth/password/reset`
- `GET /auth/google/start`, `GET /auth/google/callback`, `GET /me`, `PATCH /me` (where appropriate)

**Credits/plans:**
- `GET /plans`, `GET /me/credits`, `GET /me/credit-transactions`, `GET /me/entitlements`, `POST /jobs/quote`

**Video:**
- `POST /uploads`, `PUT /uploads/{upload_id}/parts/{part_number}`, `POST /uploads/{upload_id}/complete`, `DELETE /uploads/{upload_id}`
- `POST /videos/import-url`, `GET /videos`, `GET /videos/{id}`, `DELETE /videos/{id}`
- `POST /videos/{id}/generate`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`
- `GET /videos/{id}/transcript`, `GET /videos/{id}/suggestions`
- `GET /clips`, `GET /clips/{id}`, `PATCH /clips/{id}`, `POST /clips/{id}/render`, `GET /clips/{id}/download`

**Billing:**
- `POST /billing/orders`, `GET /billing/orders/{id}`, `GET /billing/history`, `POST /billing/webhooks/{provider}` (public ingress, cryptographically verified)
- `POST /billing/refund-requests` only if business policy supports it; never promise automatic gateway refunds without verifying provider support.

**Admin (staff authorization):**
- `GET /admin/metrics`, `GET /admin/jobs`, `GET /admin/payments`, `GET /admin/usage-costs`, `GET /admin/audit-logs`, `PATCH /admin/limits`, versioned plan CRUD, audited manual operations with reason.

**System:** `GET /health/live`, `GET /health/ready`; separate OpenAPI JSON and Swagger docs in non-production or restricted production setting as configured.

Response convention examples: `Job{ id, state, stage, progress_percent, queue_position?:null, estimated_credits, created_at, updated_at, error_code?:null }`; `Wallet{ available_credits, reserved_credits, transactions[] }`; clip revision edits are version-checked (`If-Match`/revision number) to prevent concurrent overwrite. Never expose secrets.

## H. Processing pipeline and job state machine

```
CREATED -> UPLOADING/IMPORTING -> VALIDATING -> READY
READY -> CREDIT_RESERVED -> QUEUED -> EXTRACTING_AUDIO -> TRANSCRIBING
-> ANALYZING -> SUGGESTIONS_READY -> RENDER_QUEUED -> RENDERING
-> COMPLETED (credits settled, outputs available)

Any transient phase -> RETRYING -> previous safe phase
Any phase -> FAILED (credits released) / CANCELED (credits released)
```

Enforce legitimate state transitions in one state-machine module. Job stages are checkpointed/idempotent. Provider response cache prevents repeated billable calls on queue re-delivery. Cancellation cannot interrupt all subprocesses instantaneously but should stop newly scheduled expensive actions and terminate render subprocess safely when possible. Progress is based on actual milestones; don't fabricate percentages.

## I. Media and content implementation detail

- Deepgram: official prerecorded API/SDK. Extract mono speech-appropriate audio and request word timestamps, punctuation, optional utterances/diarization as supported by selected model; do not assume every add-on is free. Record provider duration and expected billing.
- Gemini: supported official API/SDK and a pinned configurable model (choose one available to user's account); Pydantic-validated structured output for clip start/end, hook, score, reason, title, hashtags. Constrain candidates to recorded words, source time and clip-length limits; batch/chunk transcripts with overlap only if necessary. Respect provider rate limits, usage quotas, budget and retries. Never rely on guessed model IDs.
- FFmpeg: call with `subprocess.run([...], shell=False)`, sandbox execution, CPU/resource/time limits, safe caption generation (ASS/subtitle escaping), validate output with ffprobe, make 9:16 H.264/AAC clips with configured bitrate/preset. No arbitrary user filter strings/commands. Reframe with sampled face detection on CPU and temporal smoothing; fall back to center crop. Captions generated from transcript words and editable revisions.
- Reframe/caption quality targets: text stays within safe zones, no zero-duration captions, reasonable contrast, clip audio sync, visually stable crop, deterministic repro, no silent output when input has audio. Provide representative tests, documented subjective visual QA checklist and known limitations.

## J. Privacy, security and ops

- Threat model: JWT/session theft, login abuse, OAuth CSRF, IDOR/private media exposure, SSRF/rebinding, malicious video parser, FFmpeg option injection, zip bombs/resource exhaustion, upload races, job replay, wallet races, fraudulent notifications, admin privilege mistakes, secret leaks.
- Restrict media filesystem permissions and container capabilities; non-root app/worker, memory/CPU limits, filesystem quotas or capacity checks, isolation from database and Redis network ports. Enforce no arbitrary URL fetch on behalf of users.
- HTTPS/HSTS, secure headers, permitted CORS, correct proxy headers, CSRF protection, per-user/IP rate limits, auth-email throttling, high-entropy tokens, audit trails, prevent user enumeration on forgotten passwords.
- Logging: structured request/job IDs, sensitive fields redacted, account financial events auditable, PII minimal. Metrics: queue depth/wait, provider 429s, video success/failure, CPU/peak RAM/storage, total paid provider costs, cost per source minute, contribution margin estimate.
- Backups: nightly encrypted Postgres off-server and essential config (not plain secrets), backup verification and restore rehearsal; retention and privacy deletion process for videos, transcripts, outputs, users, audit data according to policy.
- Compliance: provide Terms, Privacy Policy, subprocessor disclosures, creator ownership attestation and content takedown workflow placeholders for legal review before launch. No claim of legal compliance without review.

## K. Environment placeholders

Use `.env.example` (never real keys):

```
APP_ENV=development
PUBLIC_APP_URL=http://localhost:3000
API_PUBLIC_URL=http://localhost:8000
DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@db:5432/zoclip
REDIS_URL=redis://redis:6379/0
SESSION_SIGNING_SECRET=SET_A_LONG_RANDOM_SECRET
CSRF_SECRET=SET_A_LONG_RANDOM_SECRET
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
SMTP_HOST=
SMTP_USER=
SMTP_PASSWORD=
GEMINI_API_KEY=
GEMINI_MODEL=
DEEPGRAM_API_KEY=
PAYMENT_PROVIDER=mock
PAYMENT_MERCHANT_ID=
PAYMENT_MERCHANT_SECRET=
PAYMENT_WEBHOOK_SECRET=
ENABLE_LIVE_PAYMENTS=false
ENABLE_TRIAL_CREDITS=false
MAX_VIDEO_MINUTES=120
MAX_UPLOAD_BYTES=4294967296
DISK_MIN_FREE_GB=20
MAX_RENDER_CONCURRENCY=1
MAX_AI_CONCURRENCY=2
MONTHLY_API_COST_BUDGET_USD=
DAILY_API_COST_BUDGET_USD=
```

Read defaults carefully and validate configuration at startup. Do not allow insecure placeholder secrets in production. Support local mocked provider mode for full end-to-end automated tests without spending real money.

## L. Acceptance criteria before calling this production-ready

1. New verified user can login; OAuth Google works with actual configured identity provider; passwords reset securely; logout revokes session; CSRF and rate limits tested.
2. Alice cannot read/update/download Bob's video, transcript, job, clip, wallet, invoice, or payment.
3. Paid credits are granted once on verified payment despite 10 identical webhooks; a fake success redirect grants zero credits.
4. Two concurrent jobs against limited balance cannot overdraw. Reserve/settle/release operations are idempotent despite worker crash and retry.
5. Upload and direct supported HTTPS URL work; malicious/private-network URL blocked; oversized/overlong/unreadable video rejected safely.
6. Actual representative 10/30/60/120-minute sample uploads produce properly framed/captioned verified video outputs on test infrastructure as resources permit; real-provider integration tested after credentials entered privately.
7. All provider failures leave job clearly retryable/failed and credits correctly released; no infinite retry loops.
8. Deleting/expiring source removes temporary artifacts and inaccessible media; no public files; backup and restore tested.
9. API OpenAPI spec, sample requests/responses, auth/cookie rules, error codes, SDK-safe route definitions and handoff document for Next.js v0 frontend are generated from real implementation.
10. Compose deploy can run on 4-vCPU/8-GB Ubuntu 24.04; deployment runbook describes HTTPS, worker counts, disk guard, backups, email, OAuth callbacks, provider usage limits, payment live switch, security tests and rollback.
11. Unverified gateway and business terms remain clearly marked **NOT LIVE** rather than fabricated.

## M. Unresolved commercial decisions — not blockers for code scaffolding

- Actual merchant gateway + onboarding (JazzCash, Easypaisa, or other licensed payment provider), merchant rates, signing/callback docs, settlement and supported recurring billing.
- Plan prices and credit grants in PKR; margin target and export quotas from benchmarks. Seed development-only, illustrative catalog; do not silently publish final prices.
- Domain, sender email, privacy/retention schedule, content terms, business identity. Configure through environment/admin as far as practical.
- Source-specific authorized video-link integrations beyond publicly downloadable direct HTTPS media URLs.
- Whether future plans need team accounts, subtitles languages, 1080p exports, multi-person face tracking, watermark options, premium B-roll, scheduled social posting. Explicitly not required in MVP.

## N. Official references for implementation

- Gemini structured JSON: https://ai.google.dev/gemini-api/docs/structured-output
- Deepgram prerecorded transcription: https://developers.deepgram.com/docs/pre-recorded-audio
- Deepgram utterances: https://developers.deepgram.com/docs/utterances
- JazzCash merchant sandbox documentation (not a guarantee of merchant access): https://sandbox.jazzcash.com.pk/SandboxDocumentation/v4.2/index.html
- FastAPI docs: https://fastapi.tiangolo.com/
- FFmpeg documentation: https://ffmpeg.org/documentation.html

**Instruction:** treat provider URLs/SDK APIs/prices as version-sensitive; validate against current official documentation when implementing. No secret credentials need be given to Codex in a prompt.
