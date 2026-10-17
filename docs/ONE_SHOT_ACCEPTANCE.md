# One-shot acceptance preparation — 2026-10-13

Final authorized attempt (2026-10-14): [actual execution result](LIVE_ACCEPTANCE_RESULT_2026-10-14.md)
is BLOCKED at the resource/worker gate, before any provider request, upload or
credit reservation. AI disabled and breaker=true verified; original one credit
and all data preserved. No retry or second test was performed. Earlier preparation
readiness below is not a live acceptance pass.

Latest actual state (2026-10-14): [preparation complete](ACCEPTANCE_READY_2026-10-14.md).
Approved Gemini 3.1 amendment applied; exactly one public Deepgram metadata GET
returned a verified fixed English batch version 2025-07-31.0. Five rates and the
USD 0.05 breaker=true policy installed through audited admin routes; original
one-credit allowance/customer preserved. 70 offline checks pass. AI remains
disabled and live approval false. Older missing-version/rate findings below are
historical; explicit breaker-opening/live-run authorization is still required.

2026-10-14 focused compatibility proposal:
[Gemini 3.1 replacement and Deepgram metadata discovery](PROVIDER_COMPATIBILITY_ADDENDUM.md).
User confirms 3.1/3.5 visible and Nova-3 English batch available. Proposed 3.1
rates/request changes are documentation only; fixed Deepgram pin remains unknown.
No provider API call, financial/control change or AI enablement occurred.

Approved provisioning update: [actual local provisioning](LOCAL_ACCEPTANCE_PROVISIONING.md).
Separate audited local admin and exact one-credit free-plan configuration are
now applied. 53 offline tests pass. Five rates/USD 0.05 policy remain uninstalled
because verified Nova-3 English batch version/account-rate evidence is absent.
AI stays disabled; breaker remains open. Earlier no-admin/no-credit snapshots
below are historical. The approval sheet itself remains unchanged.

Latest proposal: [one-shot approval sheet](ONE_SHOT_APPROVAL_SHEET.md) supplies
the reviewed local-admin bootstrap design, exact one-credit test terms, five
proposed rates, USD 0.05 policy and audited breaker procedure. Nothing in that
proposal has been provisioned or installed; external account/version evidence
and explicit approvals remain required. It supersedes earlier financial proposals.

**Infrastructure and offline guard ready; live execution remains blocked.**
M1–4 and all previous working-tree changes are preserved. No live Gemini or
Deepgram request, AI_ENABLED change, production billing change, deployment,
commit, push, database reset or existing-data deletion occurred.

## Latest account/model preparation — 2026-10-13

The user confirmed English speech. Fresh ffprobe reports AAC-LC, mono, 44,100 Hz,
fltp sample format, approximately 65,822 bit/s; audio duration 26.702925 seconds,
container duration 26.735042 seconds. The known sample SHA-256 is unchanged.
The existing extraction stage converts this to 16 kHz mono PCM signed-16 WAV;
the AAC source does not need to be replaced. No upload or provider call occurred.

Applied only these private backend .env fields:

```text
GEMINI_MODEL=gemini-2.5-flash-lite
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=en
```

DEEPGRAM_VERSION remains empty and AI_ENABLED remains false. Both keys are
present and byte-for-byte unchanged. All other dotenv values, including payment,
trial, email and financial-related settings, were verified unchanged. The .env
file was edited in place to preserve its existing permissions and is Git-ignored.

Version conclusion: leaving it unset is safe for disabled preparation, **not for
running the current application**. Deepgram's API documents an omitted version
as latest, but ZoClip requires a nonempty version before enablement, its adapter
currently always supplies the version query parameter, and the one-shot driver
rejects empty/latest/beta. An empty query value is not the same as omission.
Do not guess a dated version, substitute a streaming example, or relax those
guards. Obtain a verified Nova-3 English batch pin from account/support evidence.

Created exactly one isolated **customer** through the existing CSRF/register/
verification/login/profile/logout routes using the existing development-mailbox
adapter. This is local development verification, not proof of real email delivery.
Only that in-process app used the mailbox override; persisted EMAIL_MODE stays
disabled. No direct user insert, verification bypass, admin promotion, trial
grant or financial seeding was used. Password/verification tokens were never
printed. Random credentials and user ID are saved privately in ignored:

```text
backend/var/live-ai-readiness/acceptance-account/account.json
```

The directory has inheritance disabled and access limited to the current Windows
user and SYSTEM. Mailbox tokens remain private and were consumed by the normal
routes. The initial post-check expected the wrong role label; corrected it to the
actual customer contract and reused the same account. The normal password-reset
workflow revoked the abandoned session, then login/profile/logout/expired-session
checks passed. Final read-only checks show one verified customer, zero admins,
zero active authenticated sessions, zero wallets/ledger rows, zero plan prices,
rates, policies, jobs, outbox entries, requests, spend attempts and provider usage.
No credits were granted. PostgreSQL/Redis are reachable; breaker open/policy absent.

The prior 42 offline guard checks remain historical evidence; they were not rerun
for this configuration/account-only work. Fresh checks are sample ffprobe/hash,
configuration validation/key preservation, actual auth workflows, private ACL/Git
ignore and read-only service/financial-state queries. Existing HTTPX dependency
warnings remain. No application code changed in this follow-up.

### Exact remaining manual actions

1. In the provider account consoles, confirm this Gemini project's access to
   gemini-2.5-flash-lite without sending a prompt, and obtain Nova-3 **English,
   batch-capable** version evidence from Deepgram console/support. Share only
   model/version/access facts, never keys. Public documentation cannot authenticate
   these credentials or prove account access. No metadata API was called.
2. Save only the verified DEEPGRAM_VERSION after review; keep AI_ENABLED=false.
   Re-run scripts/ai_readiness.py. Its sole missing model field is currently version.
3. Approve a controlled, audited **isolated local admin provisioning procedure**.
   There is no admin account or public/self-service bootstrap endpoint. The
   customer was not elevated. Financial endpoints require authenticated admin
   RBAC, CSRF, reasons and idempotency; do not bypass them or invent a bootstrap
   command. This remains a prerequisite to configuring the isolated finances.
4. Approve numeric test-plan consumption rules and the exact one-quote credit
   allowance. Use POST /api/v1/admin/plans/{plan_id}/versions for reviewed terms
   and POST /api/v1/admin/users/{user_id}/credit-adjustments for an explicitly
   authorized, reasoned test-only positive adjustment. No fake payment evidence,
   automatic trial or commercial price is implied. The 27-second/one-output,
   zero-edit/caption/reframe quote needs credits_per_minute + credits_per_output
   + captions_credits + reframe_credits; there are no existing rules to evaluate.
5. Confirm actual account rates and approve the five cost-rate versions using
   POST /api/v1/admin/cost-rates: Nova-3 monolingual minute 0.0043 USD;
   Gemini input 0.0000001 USD/token and output 0.0000004 USD/token; plus actual
   positive render CPU-second and storage GiB-day allocation rates. Provider
   prices are public standard PAYG references, not account invoices. Deepgram's
   model binding must be the fingerprint of the verified model/version/options.
   Local allocation values are still unknown and must not be fabricated.
6. Approve a policy with the five real returned rate UUIDs, all five USD budget
   dimensions at decimal string "0.05", one open reservation, max_attempts_per_job=5,
   max_output_tokens=2048, input_tokens_per_second=1000, render CPU envelope 520
   and storage envelope 1. Use POST /api/v1/admin/limits/versions with breaker=true
   first; review the installed versions before any opening. None is installed now.
7. Breaker recovery: verify no unresolved HELD/UNKNOWN expenses, pending provider
   work, overspend or rate mismatch. Current counts are zero, so this is initial
   unconfigured fail-closed state, not evidence of a spending incident. After
   explicit financial approval, create a **new audited policy version** with the
   same reviewed limits/rates and breaker=false through /admin/limits/versions,
   using a new idempotency key and a reason. Do not directly UPDATE system_limits,
   reuse a key with a changed payload, erase usage or zero an uncertain expense.
   An overrun reopens the breaker; stop and reconcile before further work.
8. Separately approve the one live test, record that approval in the private
   attestation, then follow the existing one-shot commands below with real owned
   UUIDs. Confirm zero other active jobs and adequate resources again. The account
   can log in with its saved credentials even though new email delivery is disabled.

The provider-only conservative estimate remains USD 0.008655 plus actual local
render/storage allocations under the proposed USD 0.05 policy. No financial
setting, rate, credit balance or breaker was changed. Account provisioning and
English confirmation are complete; provider access/version, approved financial
configuration/admin procedure and explicit live-test approval remain blockers.

The sections below retain the earlier preparation snapshot and execution plan.

## Restored local services

The saved readiness PostgreSQL and Redis processes were absent and their
loopback ports were not listening. PostgreSQL retained an old postmaster PID
file; the prior logs showed successful startup, but no conclusive cause for the
process exit. No corruption or need to reinitialize was established.

Restarted the **same** PostgreSQL 17 cluster using its saved data directory,
127.0.0.1:55439, max_connections=20 and shared_buffers=32MB. PostgreSQL handled
its own stale control state; no file was manually deleted. Existing Windows
PostgreSQL services/data were untouched. Windows Start-Process -Wait initially
waited for the running server's descendants; the completed command's waiting
shell was released without stopping PostgreSQL. Future launch supervision should
wait on the pg_ctl process itself rather than the server process tree.

Restarted the installed Redis binary with its **existing** relative redis.conf,
working directory and private password on 127.0.0.1:56389. Updated only the saved
Redis PID metadata. Existing configuration disables Redis persistence; it is a
transport/cache, not the authoritative ledger. No FLUSH/reset command was used.

Existing service data/configuration remain under:
backend/var/live-ai-readiness/services-62f5c79dabb24c14a6d6fc1488390833/.
Its state.json contains private credentials and must not be printed/shared.

Fresh read-only checks:

| Check | Result |
|---|---|
| PostgreSQL connectivity | PASS |
| Migration head/current version | 7b37ea061d28 |
| Read-only Alembic drift check | PASS: no new upgrade operations |
| Redis PING / DB 0 size | PASS / zero keys |
| Users/wallets/ledger/entitlements | Zero rows; no test account or credits |
| Videos/jobs/outbox/provider requests/spend attempts | Zero rows; no pending work |
| Price versions / cost rates / cost policies | Zero rows |
| Circuit breaker / policy binding | Open / absent |

The restored services are left running; no API, RQ worker, maintenance scheduler
or live acceptance executor was started. Do not start a general queue consumer for
this acceptance. The read-only `inspect` command below can recheck the target.

## Implemented safety boundary

- scripts/acceptance_once.py is a native, single-job driver: inspect, sample upload
  validation, one-time binding, two AI checkpoint advances and one approved render.
  It never drains Redis, runs broad maintenance, seeds data or modifies payments.
- Binding is fixed to the isolated development database/media root, one owner,
  PROCESS job, video, known sample SHA-256 and reviewed public request parameters.
  It rejects other active work, moving Deepgram aliases, multiple analysis chunks,
  multiple candidates, re-exports and unapproved live execution.
- The fixed ignored acceptance-binding.json is created exclusively and fsynced
  before binding commits. Per-phase entered markers are also exclusive/fsynced.
  Missing/partial/conflicting state fails closed. There is no reset/retry flag.
- src/zoclip/ai/acceptance.py adds a job-checkpoint dispatch map. The existing
  paid-request boundary locks the PostgreSQL wallet/job, verifies request history,
  consumes one slot for that provider and **commits before network IO**.
- This guard is honored by normal/restarted workers too, not merely by the CLI.
  A consumed slot cannot resend even with the same request ID. Prior request
  history also rejects another attempt if checkpoint slot data were damaged.
  Ordinary jobs retain their previous behavior.
- A guarded 429 is recorded and stops immediately without provider requeue.
  Timeouts/unknown outcomes keep their financial exposure and never authorize
  another call. Worker recovery may reconcile checkpoints, but cannot redispatch
  a consumed provider. A crash before a send can waste its slot; safety wins over
  automatic completion. Do not delete guard records to recover a lost run.
- The CLI requires --allow-paid, ZOCLIP_ALLOW_PAID_ACCEPTANCE=1 and the existing
  private attestation's live_processing_approved boolean to be true. The flag is
  currently false. Only after these gates would it construct enabled in-process
  Settings for the AI phase; persisted AI_ENABLED remains false. That branch has
  not been executed with real credentials.
- Transcription success is checkpointed before analysis in the existing pipeline.
  The driver advances exactly these two stages, requiring a recorded successful
  transcription receipt before the Gemini stage. This is not a provider retry.
- The script emits safe status/error classes/codes, never keys, provider response
  bodies, passwords or connection URLs. No schema migration or endpoint change.

## Verification

The last full offline gate passed **38 tests** (29.72s); four subsequently added
approval-gate cases passed separately (0.30s). **42 distinct checks passed**.
The combined command now selects all 42; it was not redundantly rerun after the
four approval-only tests passed. Two existing HTTPX deprecation warnings remain.
Earlier failed test attempts are not counted as passes.

Coverage includes both providers' 429/timeouts/crashes, PostgreSQL-consumed slots
visible before mock dispatch, concurrent independent DB connections, worker lease
recovery/restart without another request, native two-stage advancement, stopped
analysis after a rejected transcription, exclusive phase files, changed binding
refusal, default-job behavior, strict recorded approval, auth/header/body/error
contracts, configuration refusal and OpenAPI consistency.

The verifier excludes live provider keys and blocks external sockets/DNS; only
the isolated PostgreSQL loopback port is allowed. Tiny FFmpeg fixtures and mock
providers are used. It forward-migrates **new generated schemas in the saved
separate mock database**, preserves them afterward and never runs the existing
reset/drop fixtures. No readiness/production ledger rows were seeded.

Evidence is ignored under var/acceptance-guard-tests-*/, including the final full
run var/acceptance-guard-tests-1d0fdf2bd81d4b9b815301f9b3045225/results.xml.
The earlier 36-case run and diagnostic schemas are preserved as well.
Ruff check/format and mypy (73 application/driver/verifier files) pass. The native
read-only inspect command passes; the AI CLI without --allow-paid refuses execution.

## Account/model readiness and cost

No provider metadata API was called because the task explicitly forbids live
Gemini/Deepgram requests. Public documentation can establish supported contracts,
not whether these keys/accounts have access. Gemini's model page restricts 2.5
access to prior active users. Deepgram's public examples do not establish this
account's English batch version. Account console/support evidence is still needed;
any metadata API discovery requires separately resolving the no-request constraint.

Both private keys remain present; GEMINI_MODEL, DEEPGRAM_MODEL and DEEPGRAM_VERSION
remain unset. Target names are gemini-2.5-flash-lite and nova-3; leave the version
unset until a verified English batch pin is available. Existing request-format
deprecation/account compatibility limits are detailed in PROVIDER_READINESS_VALIDATION.md.

Fresh sample probe/hash: test-media/sample-live-test.mp4, 2,828,785 bytes,
26.735042 seconds, 720x1280 H.264/AAC, SHA-256
281841b42e88e04b3eaf4f361111550e4517e477c30f069e754bb5ee884bc3d0.
The existing source-rights record is preserved; live approval remains false.
Intelligible English speech/content still needs private human confirmation before
using the proposed English model configuration; ffprobe does not establish that.
No new copy, upload or AI output was created. F: free is about 85.43 GiB; last
RAM snapshot was 1.36 GiB available. Do not infer long-video/build/Chrome capacity.

Provider-only conservative admission estimate for exactly one call each:
**USD 0.008655**, using one rounded-up Nova-3 monolingual minute at USD 0.0043,
35,358 bounded input units at USD 0.0000001/token and 2,048 output tokens at
USD 0.0000004/token. Add 520 * actual render CPU-second allocation rate plus
1 * actual storage GiB-day allocation rate. Proposed total budget: USD 0.05,
not applied. This is not a guaranteed provider-invoice ceiling; actual account
rates, taxes/FX and unexpected billed usage remain relevant.

Before any live approval, the isolated DB still needs reviewed real rate versions
for all five components, actual positive local allocation rates, the five USD 0.05
budget dimensions, max_open_reservations=1, max_attempts_per_job=5, matching model/
option bindings and policy rate UUIDs. Five means expense rows, not requests.
Keep the breaker open until explicitly approved configuration/execution.
No test account, plan terms or credit grant was fabricated. Required customer
credits for the 27-second, one-output, zero-edit quote are the actual plan's
credits_per_minute + credits_per_output + captions_credits + reframe_credits.

## Exact commands and stop conditions

Safe now, from a normal local Windows terminal with access to the private files:

```powershell
Set-Location D:\ZoClip-Project\backend
.venv/Scripts/python.exe scripts/acceptance_once.py --phase inspect
.venv/Scripts/python.exe scripts/verify_acceptance_offline.py
.venv/Scripts/python.exe -m ruff check src scripts/acceptance_once.py scripts/verify_acceptance_offline.py tests/test_acceptance_once.py
.venv/Scripts/python.exe -m mypy src scripts/acceptance_once.py scripts/verify_acceptance_offline.py
```

Future procedure — **not authorized or executed**. Resolve all account, version,
rate/policy/credit/resource blockers and record explicit paid-test approval first.
Keep AI_ENABLED=false in .env and the shell. Use a dedicated local account/browser
or private cookie session, and the existing M3/M4 UI/API contracts; do not rebuild
the upload/editor or run a general worker. If an API is needed, use a separate free
loopback port rather than replacing an existing server:

```powershell
$env:API_PUBLIC_URL='http://localhost:8010'
.venv/Scripts/python.exe -m uvicorn zoclip.main:create_app --factory --host 127.0.0.1 --port 8010
```

The existing frontend must point at http://localhost:8010 for this separate run.
Start/rebuild it only when resources permit. Auth cookies/CSRF remain required.

1. Upload only the known sample through POST /api/v1/uploads, checksum part PUTs,
   then POST /uploads/{upload_id}/complete. Capture its actual VALIDATE job UUID.
2. Run validation once. Get the normal 27-second/output_count=1/edit_count=0,
   captions=true/reframe=true quote and explicitly confirm generation through the
   existing UI/API. Capture the resulting PROCESS job UUID. No worker auto-start.
3. Bind that exact queued job, then, only with the explicit live approval recorded,
   run the AI phase. IDs below must come from the actual authenticated API responses:

```powershell
# $ownerId, $validationJobId, $processJobId are real owned UUIDs, not invented IDs.
.venv/Scripts/python.exe scripts/acceptance_once.py --phase validate --owner $ownerId --job $validationJobId
.venv/Scripts/python.exe scripts/acceptance_once.py --phase bind --owner $ownerId --job $processJobId
# ONLY after explicit live approval, reviewed account/version and installed controls:
$env:ZOCLIP_ALLOW_PAID_ACCEPTANCE='1'
try {
    .venv/Scripts/python.exe scripts/acceptance_once.py --phase ai --owner $ownerId --job $processJobId --allow-paid
} finally {
    Remove-Item Env:ZOCLIP_ALLOW_PAID_ACCEPTANCE -ErrorAction SilentlyContinue
}
```

4. Inspect the actual transcript/highlight. Create one draft, save classic captions
   and center framing, then explicitly approve exactly that clip through
   POST /jobs/{processJobId}/renders. Do not request paid/prepaid re-exports.

```powershell
.venv/Scripts/python.exe scripts/acceptance_once.py --phase render --owner $ownerId --job $processJobId
```

5. GET the owned completed revision through /clips/{clip_id}/download?revision=N
   using its private cookie session. Verify the MP4, caption/audio/framing quality,
   one RESERVE/one SETTLE, no held credits and exactly one recorded dispatch per
   provider. Private download and subjective quality remain live acceptance checks.

Stop on missing approval/configuration, changed sample/model/binding, any other
active work, insufficient credits/disk/budget, 429, timeout, ambiguous outcome,
invalid/empty transcript/suggestions, crash, existing phase marker or unexpected
state. Ctrl+C/terminate only the selected executor if needed; never restart its
consumed phase, delete markers, clear PostgreSQL slots, create a replacement job
or run a second executor. Inspect receipts and reconcile finances manually under
separate authorization. Remove temporary opt-in and leave AI_ENABLED=false.

## Remaining blockers

Account-specific Gemini access/key validity; verified Nova-3 English batch version;
unset model configuration; missing isolated account/credits/plan terms; missing
actual rates/local allocations/budget policy; open breaker; explicit paid-test
approval and its private record. Live rendering/download/quality and actual
provider responses remain untested. The environment is **not yet ready for a
live test**, despite restored infrastructure and passing offline guard verification.

Sources: [Gemini model availability](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite),
[Deepgram version semantics](https://developers.deepgram.com/docs/version),
[Deepgram metadata](https://developers.deepgram.com/guides/fundamentals/model-metadata),
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Deepgram pricing](https://deepgram.com/pricing).
