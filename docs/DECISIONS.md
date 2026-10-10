# ZoClip decision register

Phase 0 decisions, with Phase 1 through 3 additions below. Accepted means design default;
implementation evidence lives in IMPLEMENTATION_STATUS.md. No payment/AI provider
integration, current fee or model availability claim is made.

| ID | Decision/default | Rationale / revisit gate |
|---|---|---|
| D01 | Modular monolith, Python 3.12 and specified FastAPI/PostgreSQL/RQ stack | Fits single CPU VPS; dependency locks in Phase 1 |
| D02 | Sync sessions per request/task; short locked transactions | Clear financial consistency, no shared sessions |
| D03 | PostgreSQL outbox and job leases; Redis is delivery only | Recover DB/queue crash gap and duplicate workers |
| D04 | One AI and one render worker initially; two FFmpeg threads | Conservative 4-vCPU default; raise only with measurements |
| D05 | 120 min, 4 GiB, 20 GB headroom; atomic disk reservations | Limits coexist; capacity check may reject smaller files |
| D06 | Initial 40 GiB retained media, two ingestion slots, queue cap 10 | Provisional bounded working set, tune by benchmarks |
| D07 | PKR integer paisa, integer credits, fixed precision USD | Currency and credit quantities are distinct |
| D08 | Locked append-only wallet ledger and unique operations | Reserve once; settle successful deliverable or release once |
| D09 | Atomic spend holds include in-flight/unknown provider exposure | Prevent parallel calls overspending configured budgets |
| D10 | Paid work disabled without configured rates/models/budgets | No reliance on free quotas or guessed commercial economics |
| D11 | Prepaid packs/30-day entitlement; trial disabled | No assumed auto-recurring merchant support |
| D12 | Live payments disabled; mock only explicit dev/test | Merchant, current docs, verification and approval pending |
| D13 | Direct HTTPS allowlisted media only; compliant future adapters | No universal URL downloading; mandatory SSRF boundaries |
| D14 | Private local UUID storage; authenticated downloads initially | Owner isolation and revocation; object-store interface later |
| D15 | Host-only secure API cookie, same-site subdomains, explicit CORS/CSRF | Later v0 frontend consumes backend authority |
| D16 | 720x1280 H.264/AAC; selected intervals only; center fallback | CPU feasibility; actual caption/crop quality requires QA |
| D17 | Seven-day source/transcript/output TTL; 24h incomplete uploads | Provisional configurable policy; business/legal approval needed |
| D18 | Suggestions do not imply rendered completion or full-job settlement | Phase 4 is intermediate; hold timeout policy before public use |

## Pending decisions and operational risks

- Merchant provider, official verification/query/refund docs, onboarding approval,
  fees, settlement timing, late-payment policy and chargeback procedures. No live
  provider or recurring billing is promised. Implement disabled interface until verified.
- Approved PKR prices, credit conversion, output/edit quotas, spend ceilings,
  margin targets and USD/PKR reporting rate source. Need measured paid-provider,
  failed-job, compute, storage and gateway costs; no profitability claim.
- Domain, sender email, SMTP, Google configuration and callback URLs. Configure
  privately later; disabled capabilities must fail clearly, not fake success.
- Allowed direct-media hosts and permissions; other platform ingestion requires
  compliant adapter and product/legal review. Ownership attestation alone does not
  authorize bypassing provider protections.
- Published retention, financial/audit retention, backup destination and expiry,
  media disaster recovery, Terms/Privacy/subprocessor disclosures and takedowns.
- Exact codec/dimension/FPS bounds, scratch expansion estimates, output count caps,
  request deadlines, rate limits and max-per-job spend need fixture measurements.
- Full-job success criterion for automatic multi-clip requests and suggestions-only
  hold expiry must be explicit before billable public use; default is no partial charge.
- Remote API timeouts can mean billed-but-response-lost. Unknown attempts need
  reconciliation and retained spend exposure; do not claim exactly-once remote billing.
- Germany-hosted media and subprocessor transfers need clear customer disclosure;
  no compliance assertion before review. Urdu/English font shaping and multi-speaker
  reframe quality need representative QA.
- Shared 4 CPUs and small disk can bottleneck parser/extraction/render work; DB,
  images/logs and retained artifacts compete for the same SSD. Measurements and
  safe rejection matter more than theoretical concurrent user counts.

These are not blockers to Phase 1 scaffolding. They block affected integrations,
commercial launch or capacity claims at their respective gates.

## Phase 1 additions

- Opaque random server sessions use only hashes in PostgreSQL; no session-signing
  secret is required. CSRF also uses a random token hash bound to that session.
  Anonymous sessions protect pre-login mutations. Explicit Origin required even for curl.
- Verification/reset tokens are hashed, single-use and serialized on user/token locks.
  Password reset revokes all authenticated sessions. Session rotation locks user first.
- Argon2id 64 MiB, time cost 3, parallelism 1; at most two simultaneous hash/verify
  operations per API process. API concurrency cap 32, DB pool 2/overflow 0; UTC
  connections with 10s statement and 5s lock deadlines. These are defaults, not load results.
- Redis Lua fixed-window auth limits fail closed when unavailable. Tests use real
  PostgreSQL; fakeredis/Lua is explicit locally, real Redis is configured in CI.
- Google uses Authlib 1.8 + joserfc signature/claim validation and server-side
  single-use flow/browser binding. No automatic email-based linking: prove both
  identities through an active verified local login and verified matching Google email.
- Email modes are disabled or explicit private development mailbox. No live email
  provider is implemented; production registration/recovery stays unavailable until one is added.
- Phase 1 Compose has internal PostgreSQL/Redis, loopback API and empty AI/render
  workers. It is not the finished Phase 7 production deployment. Before production,
  split migration/runtime DB privileges; Compose's initial database owner is privileged.
- Audit mutation trigger rejects UPDATE/DELETE/TRUNCATE; database superuser schema
  access remains an operational boundary. No publicly callable role grant exists.
- Dependency ranges are in pyproject.toml, exact versions/hashes in uv.lock; no
  guessed vendor models/rates. Google OIDC/Authlib official documentation and installed
  source interfaces were checked; live Google credential verification remains pending.

Phase 1 infrastructure follow-up (2026-10-10): local Windows-port Redis/RQ and
PostgreSQL tests are supplemental evidence only. Official Linux Docker build,
startup and both worker entrypoints remain pending. The user will install Docker
Desktop/WSL2 locally; Contabo access/configuration is not authorized. No Phase 2 work.

## Phase 2 decisions (2026-10-10)

- D19: Credit expiry disabled, unrestricted rollover. Prepaid access lasts 30 days,
  sequential renewal periods, no auto-renewal or proration. Each explicit manual
  entitlement award grants its versioned allowance once immediately. Top-ups do
  not replace paid access; Free grants never override active paid access.
- D20: Catalog identity only is seeded (four plans plus topup). Prices, quotas,
  rates and budget policy require audited staff configuration. Unapproved prices
  are usable in dev/test, blocked for new production quotes/reservations.
- D21: No automatic trial grant or customer claim endpoint. Enabling the existing
  trial setting fails closed until missing device/IP and abuse review controls exist.
- D22: REFUND explicitly distinguishes settled-charge restoration from unspent
  grant reversal via its immutable original ledger reference; both are capped.
  It is not a gateway currency refund or a chargeback workflow.
- D23: Lock order is target user -> wallet -> global system_limits. Global expense
  admission uses one PostgreSQL row mutex and SQL aggregates initially. Every
  paid/compute/storage admission includes existing holds, unknowns, retry costs
  and sunk actual costs. Unknown exposure does not disappear at a UTC boundary.
- D24: An expense admission replay never authorizes reexecution; fresh=True only
  after commit permits a future side effect. Unknown outcomes require evidence.
  Actual overruns are retained and open the breaker. Disabled accounts still
  allow financial cleanup while blocking new spending.
- D25: Methods own no commits/queue/provider effects. Phase 3 must atomically
  compose reserve with job/outbox; Phase 5 composes output completion with settle.
  Advisory frontend duration is revalidated against probed owned metadata there.
- D26: Migration dd9634e4866b preserves Phase 1 and adds immutable financial history.
  Downgrade refuses populated ledger/expense history. Runtime DB role separation
  remains a production rollout requirement; no schema-owner bypass protection is claimed.

Phase 1 Docker-pending notes above are historical; the final Phase 1 status records
its completed local gate. Phase 2 execution and exact verification follow in
IMPLEMENTATION_STATUS.md. No payment/provider integration or commercial approval
has been inferred from this financial foundation.

## Phase 3 decisions (2026-10-10)

- D27: Fixed-size zero-based streamed chunks, exact lengths and SHA-256, reordered
  parts and safe repeats. One bounded writer per upload; 60-second stream deadline,
  180-second lease and fixed 24h upload expiry. No multipart whole-file buffering.
- D28: Private UUID filesystem objects shared by API/workers/maintenance. PostgreSQL
  singleton admission protects remaining disk commitments and global/user quotas;
  actual free-space headroom cannot be configured below 20 GiB. Capacity envelopes
  are conservative and require Phase 5 validation before any rendering.
- D29: Exact host allowlist is empty by default. HTTPS/443, bounded DNS subprocess,
  numeric socket pin, actual peer check, original-hostname TLS validation, per-hop
  redirect checks, MIME/magic/byte/deadline guards and ffprobe. No platform adapters.
- D30: Validation/import completion means READY source only. PROCESS requests reserve
  under the existing Phase 2 contract and enter WAITING_ENGINE. No production mock
  deliverable or settlement. Waiting holds cancel after 24h; customers can cancel.
- D31: PostgreSQL jobs/events/outbox with fixed 900s worker fences, 660s RQ timeout,
  periodic heartbeats, max three claims and bounded transient retries. One task
  is active at a time even if extra AI workers are started. Repeated queue messages
  cannot reexecute a claimed/terminal job. Pending deliveries replay after Redis loss.
- D32: Access revocation precedes cleanup; active writers/leases delay physical
  deletion and resource release. Orphan sweep only touches generated UUID files
  older than an hour. Immutable financial and job audit records are retained.
- D33: MP4/WebM only, one supported video plus audio, bounded dimensions, sampled
  nonempty packets and finite duration <=120 minutes plus the current plan cap.
  ffprobe uses Linux resource limits and file-only protocols, no shell. This is
  validation, not a claim of full-frame decoding, malware certification or measured
  120-minute throughput. Ubuntu/Linux remains the worker runtime.
- D34: Download authorization and deletion serialize under the same owner/storage
  locks. Refresh READY/expiry under lock before opening; an already-authorized
  descriptor may finish, but deletion that wins the lock prevents a new open.
- D35: Linux fsyncs containing directories after promotion/removal before the DB
  receipt commits. Crash recovery retains parts until committed validation,
  revalidates unpublished sources, and deduplicates committed/lost-ack publication.
- D36: Canonical POST /videos/{id}/generate and compatible POST /jobs share
  idempotency. Credit estimates snapshot accepted reservations. Unknown progress
  stays null; completed ingestion alone reports 100. Future engine stages are deferred.
- D37: Transient retry uses bounded equal jitter, max three claims. Randomness is
  injectable in tests; it cannot increase attempts or authorize paid requests.
- D38: HTTPS verification uses an isolated internal Docker network with a synthetic
  globally classified address and a disposable trusted test CA. Production IP
  validation, peer pinning and TLS hostname checks remain enabled. This verifies
  real HTTPS transport without claiming public-Internet source availability.

Phase 2 was reverified before edits (115 tests, all local gates) and checkpointed
as e97c866. No prior migration or financial contract was rewritten. Phase 3 evidence
and known operational limitations are recorded in IMPLEMENTATION_STATUS.md.
