# Private staging upload failure — fixed 2026-10-15

Reported file: `Alright I woke up this.mp4`,114,549,007bytes.

## Exact root cause and evidence

The real staging database contained zero upload sessions, uploaded parts, source
videos and ingestion jobs. The private media volume contained zero files. There
was therefore no completed transfer or finalization result to refresh into the
video list, and no server copy of the reported file to recover/delete.

The deployed `POST /api/v1/uploads` path called `ingestion_gate`, which required
`credits.active_price` even for non-billable upload/validation. Staging had no plan
price versions, by design: AI, credits/grants and payments were kept closed.
Reproducing admission with the exact reported size raised HTTP503,
`plan_unconfigured`, before creating any durable upload/video record. Recent
staging logs showed repeated failed POST503 responses and no part transfers.

The browser runtime was not exposed by the browser tool, so live DOM, localStorage,
DevTools requests and the exact original response body were not directly captured.
Shipped source establishes the request order: local SHA-256 of the entire file,
then upload initiation, parts, completion. The UI retained the100% checksum bar
when initiation failed, making local preparation look like a completed upload.
Logs are intentionally redacted and do not include request paths; the rollback
service reproduction provides the exact error code/path attribution.

Finalization was never reached for the original attempt. The existing frontend
already invokes `onJob` and `onChanged` after a successful completion response;
these refresh the owner-scoped video list. The job monitor refreshes that list
again as validation state changes. No missing-success-refresh bug was found.

## Changes

- Upload admission and validation now share `source_duration_limit`. Only when
  `PRIVATE_STAGING=true`, the catalog is absent, AI/payments remain disabled, and
  the existing DB spending breaker is true may upload-only validation use the
  existing120-minute hard cap. No plan, entitlement, price, quote, credit grant or
  processing authorization is created. Existing configured plan duration limits
  still apply; disabled plans are not bypassed. Public deployments retain their
  missing-plan rejection. Missing/open spending controls fail closed.
- All authentication, CSRF, ownership, checksums, multipart leases/idempotency,
  size/disk/headroom/queue/concurrency/retention limits and network restrictions
  remain unchanged. AI generation and financial paths still require their
  original controls and catalog; the ingestion fallback is not used there.
- UI progress now distinguishes local hashing, upload-session admission,
  server-confirmed bytes, and pending finalization. The session/finalization
  bars are indeterminate; failed attempts clear progress and retain safe resume
  metadata. A known missing-catalog rejection is no longer retried as a transient
  outage. Resume keys and already confirmed parts remain supported.

## Verification and deployment

- 62 backend cases passed against a newly initialized disposable PostgreSQL17
  instance, not acceptance/staging data. The new integration case exercised real
  authenticated HTTP initiation201, checksum-confirmed parts200, completion202,
  actual ffprobe validation, stored-byte hash equality and owner video-list READY.
  No prices, credit transactions or balance grants were created; breaker stayed true.
- 13 frontend upload cases passed, including100% local hashing followed by a
  rejected initiation, interrupted transfers, unchanged retry keys, resume from
  confirmed parts, and rejected finalization never becoming upload success.
- Backend Ruff/mypy, frontend Oxlint/TypeScript and Vercel production build passed.
- Backend release: `staging-20261015-uploadfix1`; app image
  `zoclip-private-app@sha256:636d41e77e80059de49edf69af994bb7aae8f6c0f4923b242182a8eecedfb409`.
  Package/version inventory matched the previous security-refresh image. Existing
  image-advisory limitations remain documented in the deployment report.
- Frontend deployment: `dpl_4S1dochetVEoCsBWEt12BkP8Tp49`, aliased only to
  `zoclip.technabeel.com`. All-deployments Vercel protection remains enabled.
- Encrypted pre-fix backup `20261015T115946-1cae0c01.json` was copied to the owner's
  PC; manifest and both ciphertext hashes matched. Manifest SHA256:
  `922ff6385a59741502206f1a5cdedf71a39cf99f645dd6bd188270bd9c7cb642`.
  No database migration, volume reset, data/file deletion or schema change.
- Real staging rollback-only admission with114,549,007bytes now passes and declares
  14parts of at most8MiB. Attempting completion without parts still fails
  `incomplete_upload`. Diagnostic records were rolled back; durable counts stayed
  unchanged at zero uploads/parts/videos/jobs/prices/credit transactions/provider
  usage. Existing wallet balances stayed zero. No user credentials were read.
- All seven services returned healthy, host checks returned `alerts:[]`, VPN
  HTTPS readiness returned200, public API TCP18443 stayed unreachable, and the
  frontend continued redirecting signed-out requests to Vercel authentication.

## Verify the original file

Keep WireGuard active. Hard-refresh `https://zoclip.technabeel.com` to load the fix
without clearing browser storage. In Videos, reselect the original file, confirm
the ownership checkbox and choose Resume upload (or Upload video if no saved
intent). Do not cancel/delete the saved upload to recover this failed attempt.

Local checksum completion is only preparation. Wait for server-confirmed bytes
to reach114,549,007, then `Upload accepted for validation` and the live VALIDATE
job. Your videos should show its row automatically, initially VALIDATING and then
READY. Source names are not part of the current backend video contract; identify
the new card by its ID/state and size. Do not request AI processing.

The owner's exact file was not re-uploaded by the agent because no browser/file
session was available. Its successful transfer remains the owner's verification
step; the authenticated full-path regression used an isolated synthetic fixture.
