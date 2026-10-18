# ZoClip decision register

2026-10-19: default transcription is local faster-whisper small/cpu/int8, with
explicit Deepgram rollback only. Gemini/selection/API shapes and all customer
financial rules stay unchanged. Offline image assets, one shared-volume inference
lock and local durable receipts avoid silent paid fallback or invented API spend.
See [operating constraints and privacy](LOCAL_WHISPER.md). CostRates remain pending
separate owner approval; no financial configuration is installed by this change.

2026-10-15: owner selected reviewer WireGuard VPN with SSH retained for operations.
Keep Docker loopback-only and use a separate systemd socket bound to wg-zoclip
plus its exact private IP, forwarding encrypted TCP to existing loopback HTTPS.
Dedicated pre-Docker nft filtering allows only named peer IPs to API TCP and
rejects other VPN input/forwarding. No Vercel private connector, default client
route, NAT, provider egress or public API is introduced. See WIREGUARD_REVIEWER_ACCESS.md.

2026-10-14 staging blocker follow-up: implement first-admin and customer reviewer
invites in a separate operator-only production/private-staging CLI, never relax
the local acceptance bootstrap. Hash retained fresh target-bound approval manifests
and identity evidence; store random token hashes, expire within one hour, globally
serialize issuance/redemption under the existing read-only financial fence and
write activation/revocation with immutable audits in the same DB transaction.
First-admin activation permanently closes bootstrap; no credits or auto-login.
An external invite-epoch UUID invalidates old delivery tokens after restores.
Retain earlier managed reviewer SSH topology unless owner selects another network;
document browser/hosts/TLS/permission gates explicitly and add a manual browser
readiness probe. Vercel hosts UI only, with All Deployments protection configured
externally. No infrastructure/provider/acceptance execution authorized or performed.

2026-10-14, Phase8 M6: owner chose same-site frontend/API subdomains and SSH
tunnel access initially. Prepare a separate private Compose override and proxy
profile that allows RBAC-protected admin routes at the same browser API origin.
Keep base deployment intact, app networks internal, all integrations disabled and
spending blocked. Production public signup defaults off; private staging startup
requires existing breaker=true and refuses admin attempts to open it. Vercel must
protect all deployments externally. No secret, account, credit, policy or paused
acceptance evidence is changed. The production invite/first-admin path needs a
separate audited implementation after owner identity/delivery policy selection;
the local acceptance bootstrap must never be generalized to staging. See the
[M6 runbook](PHASE8_PRIVATE_STAGING_RUNBOOK.md) for approval boundaries and blockers.

2026-10-14: Recover only the proven pre-dispatch resource-gate failure through
the [scoped continuation](ACCEPTANCE_CONTINUATION.md). Preserve the historical
workflow guard and all provider slots. Reuse the immutable PostgreSQL audit table
with a serialized consumption event and full receipt SHA-256 event, plus an
exclusive local fence and an in-memory start permit. Ambiguous commits/crashes
remain consumed. No schema migration, HTTP recovery route, automatic approval,
provider retry or guard reset. Implementation approval does not authorize live
execution; fresh explicit approval is required before any consumption.

User-selected live-test media now uses new private F:\ZoClip-LiveAI storage,
keeping the project and new isolated service data on D:. This resolves real disk
admission without deleting prior data or changing capacity safeguards. A separate
26.74-second bounded local input copy preserves the original video. New loopback
PostgreSQL/Redis are independent of existing Windows services. Keys remain private,
AI disabled and the budget breaker open; no provider model/version or real rate
is fabricated to complete readiness. Current evidence: PHASE8_LIVE_AI_READINESS.md.

Live AI preparation stays disabled and separate from mock acceptance. Keys belong
only in ignored backend configuration with restricted local permissions. Model
selection remains unset until account access and the existing request body are
reviewed; newer Gemini IDs are not assumed compatible. A proposed USD 0.05 isolated
test ceiling requires actual versioned rates, all PostgreSQL budget dimensions,
real disk/RAM capacity and explicit approval. No rates or budgets were applied.
See [offline readiness and manual gates](PHASE8_LIVE_AI_READINESS.md).

M4 frontend options derive from actual OpenAPI: three caption presets, four framing
modes, and fixed 9:16 720×1280 MP4 output. Edits use complete Preferences/If-Match;
confirmed render requests preserve keys, while downloads require completed owned
jobs and explicit revisions. No financial/provider/API migration was introduced.
See PHASE8_EDITOR_MILESTONE.md for evidence and synthetic-capacity test limitations,
and PHASE8_LIVE_AI_PLAN.md for the separately approved live-provider gate.

Phase 0 decisions, with Phase 1 through 6 additions below. Accepted means design default;
implementation evidence lives in IMPLEMENTATION_STATUS.md. AI REST adapters have
local simulator verification; live account/model acceptance remains unverified.
Payment verification is local mock-only; merchant integration and fees remain unverified.

Phase 8 M3 connects the existing upload/import/quote/generation/job contracts;
see PHASE8_MEDIA_MILESTONE.md. Upload hashing uses incremental 1 MiB reads and
one server-sized part at a time. Owner-scoped local resume metadata and confirmed
generation keys survive uncertain acknowledgments. Background identity checks
preserve mounted transfers while failures still fail closed. No backend schema,
financial invariant, provider switch, new dependency or deployment decision changed.

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

## Phase 4 decisions (2026-10-10)

- D39: REST adapters use locked HTTPX, fixed official HTTPS destinations, header
  keys, no redirects or implicit retries. Models/versions are operator supplied,
  disabled by default. Deepgram options fingerprint binds reviewed rates; Gemini
  input/output rates bind the configured model. No account availability is assumed.
- D40: Each claim makes at most one paid request after committed admission.
  Gemini input/output holds are one atomic pair. Fsynced private receipts permit
  recovery without another paid call; missing evidence retains UNKNOWN exposure.
  Only confirmed 429 rejection or proven local nondispatch is treated as zero usage.
  5xx/timeouts/auth errors are conservative unknowns requiring evidence, not retries.
- D41: Source/owner/options/prompt-scoped caching; bounded overlapping transcript
  chunks with absolute word times; validated/ranked/nonoverlapping suggestions.
  Empty/bad output fails without invented content. Semantic usefulness needs QA.
- D42: Suggestions remain SUGGESTIONS_READY with HELD credits and null progress;
  no render, output or SETTLE. Customer cancellation or 24h intermediate-hold expiry
  releases once. No Phase 5 work is authorized by this intermediate lifecycle.
- D43: Cancellation/crash recovery reconciles persisted responses or retains
  UNKNOWN before cleanup. Proven unsent admissions void. In-flight provider calls
  cannot be recalled. Privacy cleanup erases text/receipts/candidates while keeping
  financial usage/reference/hash history. Runtime media lock order is user/wallet,
  storage pool/job when needed, then system_limits; never system_limits -> storage.
- D44: Local gate uses PostgreSQL/Redis, actual FFmpeg/RQ and isolated HTTPS
  simulators with fictional keys/models/rates. Opt-in live smoke reuses normal
  admitted jobs and all budget controls, never fabricates credits. Current user
  prohibits live paid calls; the real Deepgram/Gemini provider gate remains PENDING.
  The user subsequently authorized a local Phase 4 checkpoint commit based on the
  passing mock/fixture gate. Production readiness is NOT APPROVED; the checkpoint
  does not waive real-provider verification or authorize Phase 5.

## Phase 5 decisions (2026-10-10)

- D45: Explicit immutable selection continues the original job/HELD reservation.
  One selected clip per lease, all verified before exactly-once settlement; partial
  failures release fully and hide partial exports. Separate render queue and one
  render claim globally; one AI/ingestion claim can coexist.
- D46: Non-destructive integer-ms revisions, quoted features, If-Match conflicts,
  bounded exports/prepaid edits. Prepaid render/storage expense alone may use the
  original settled evidence after durable server approval. Failed edits retain
  expense but restore allowance; a refunded original cannot fund prepaid work.
- D47: Exact selected-interval transcoding, H.264/AAC 720x1280, common seek-relative
  audio/video times, generated literal-text ASS, three presets and allowlisted fonts.
  Full output decode and bounded timing validation precede publication/settlement.
- D48: CPU OpenCV Haar sampling (24 frames/20s), face-size/prior-focus weighting,
  smoothing and explicit center fallback; no active-speaker identification claim.
  Locked OpenCV/NumPy and packaged font families; no external vision spend.
- D49: Fenced atomic output promotion and revalidation after lost DB acknowledgment;
  per-output three bounded local attempts, measured child CPU or conservative lost
  worker ceiling, integer retention units, existing all-scope spend/capacity guards.
  Source revocation/TTL governs revisions and outputs; audit/financial history stays.

## Phase 6 decisions (2026-10-10)

- D50: Reuse audited price versions; snapshot current prepaid PKR amount, credits,
  validity and fee schedule in immutable order terms. One deterministic sandbox
  checkout reference. No launch price, auto-renewal, gateway fee or profit inferred.
- D51: Only adapter-verified exact order/reference/amount/currency evidence grants.
  User -> wallet -> order locking and unique provider event arbitration serialize
  payment/entitlement/GRANT atomically, including collisions across owners. Browser
  returns grant nothing; altered event or order key payload is rejected.
- D52: Accept late delivery of payment made before expiry. Post-expiry payment or
  unavailable owner enters REVIEW without credits; only independent provider query
  plus reasoned staff accept_late may accept a late payment. Reversals are terminal,
  including when delivered before success. No unauthenticated/manual paid switch.
- D53: Verified full reversals recover fungible available credits up to the original
  unrefunded grant, append entitlement revocation, retain spent/held exposure and
  disable the account when unrecovered credits remain. No negative wallet, seizure
  of held credits, partial refund, automatic debt clearing or unrestricted unblock.
- D54: Refund intent commits UNKNOWN before provider IO. Replay never resends an
  uncertain refund; signed reversal or independent query confirms. Staff query
  reasons/results and audit events are immutable. No evidence grants zero.
- D55: MockSandboxProvider is explicit non-production, keyed signed fixture JSON.
  It performs no merchant IO; query/refund evidence is injected only in tests.
  The local helper requires opt-in and loopback/isolated host, no proxies/redirects.
  JazzCash stays disabled because current official callback/query/refund documents
  could not be verified (rejection/timeouts); no merchant contract is invented.
- D56: Migration 651ba28dacf9 appends billing tables and database term/evidence
  guards; populated downgrade refuses erasure. Existing financial rows/migrations
  remain intact. Revocations are separate from immutable Phase 2 entitlements.

## Phase 7 decisions (2026-10-10)

- D57: User authorization is private preparation only. Compose publishes two
  loopback HTTPS listeners, customer excludes admin/docs/webhooks; no VPS/DNS/SSH
  or public deployment. This narrows the earlier eventual80/443 design. AI/payment/
  email/OIDC/trial are disabled; no live secrets or provider IO in local checks.
- D58: Separate bootstrap/schema-owner/runtime PostgreSQL roles and mounted
  SecretStr files. Runtime has no DDL/TRUNCATE/migration-version authority or
  append-only UPDATE/DELETE. Application/DB/Redis/proxy run non-root, read-only,
  bounded, drop capabilities, rotated logs; one trusted static proxy peer.
- D59: One AI/one render worker, per-boot RQ identity with exact health receipt
  avoids stale registry collision after SIGKILL. PostgreSQL fences remain source
  of authority. Resource ceilings/40GiB media/20GiB headroom are planning limits;
  no video throughput claim and no scaling without measurements.
- D60: Quiesce all writers for consistent DB/media backups; stream age ciphertext,
  atomic manifest/checksums, no local decryption identity in services. Restore only
  separate empty targets; no destructive clean/downgrade. Real off-server retrieval,
  maintenance window, retention/RPO/RTO, alert delivery require operator decisions.
  Local100GB storage cannot hold a worst-case full backup alongside40GiB media;
  capacity guard refuses, requiring smaller working set/approved scratch capacity.
- D61: Monthly audited operations aggregates use recorded usage, integer PKR and
  optional versioned decimal invoice/FX/target policy with hash; estimates remain
  labeled. Duplicate notification fees count once; no invented price/profit.
  Local monitor exit status is implemented, outbound notification not configured.
- D62: Explicit staff erasure intent revokes/pseudonymizes auth, uses existing
  lease-aware media deletion, preserves finance/immutable case audit; disabled
  payment-risk status never implies consent to erasure. Migration7b37ea061d28
  refuses populated downgrade. Backups/provider retention need separate cleanup.
- D63: Rollout requires exact image and verified backup/new-empty-DB review marker.
  New-empty approval also requires an actually empty public schema. Boot/backup
  resume starts existing workload container IDs without running the migrator.
  Image rollback additionally requires current-schema compatibility and never runs
  an old migrator. Incompatible recovery is a separate empty-target restore with
  privacy and post-backup financial/provider reconciliation before promotion.
