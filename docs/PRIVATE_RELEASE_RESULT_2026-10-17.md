# Protected release result — 2026-10-17

The owner explicitly requested completing the interrupted release at the existing
private destinations. Recovered source hashes matched the completed backend build;
the build and backup were reused. No database reset, schema downgrade, paid AI
dispatch, payment activation, public API listener, or protection bypass occurred.

## Deployed

- Backend release: `staging-20261017-final1`.
- Immutable app image: `zoclip-private-app@sha256:84cf6d54b251a18111168e131ed4325ff8374d3f9f25add83c721ca80858c5c0`.
- Frontend: `dpl_GKrPNBvtPSBEhbbtg5THJ5graf1J`, READY, serving
  `https://zoclip.technabeel.com`.
- Generated frontend: `https://zoclip-3kewbiq56-faisals-projects-160572e0.vercel.app`.
- API: `https://api.zoclip.technabeel.com:18443`, VPN only.
- Alembic remains `8c42ab719e30`; no rollout migration ran. All 78 installed Python
  source hashes match the reviewed manifest. Seven steady containers are healthy.
- Systemd startup points at the new release directory. WireGuard, the dedicated
  reviewer firewall and the VPN-bound API socket remain active.

## Resulting customer behavior

The recovered implementation presents a separate landing page and customer
workspace, upload progress, a price before confirmation, automatic initial clip
rendering when authorized, and private preview/download controls. Credit checkout
honestly remains unavailable. Loading and error states no longer invent a zero
balance. Customer editor/download copy avoids internal resource identifiers.

The audited, idempotent catalog installer added four price versions. Default
processing terms charge at least 60 credits; default included credits are zero.
Retail packages remain unapproved. The retained 26-second source now produces a
configured 60-credit preview. A normal quote was also verified in a rolled-back
transaction. Neither check created durable quotes, financial entries or work.
Private staging explicitly shows generation paused; it offers no paid dispatch.

## Verification and data preservation

- Existing 114,549,007-byte READY video remains present with SHA-256
  `4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80`.
- Existing user, source and validation job remain. No processing job, rendered
  output, clip, credit grant/reservation/transaction, provider usage, spend attempt,
  billing order or paid entitlement was added. Wallet available/reserved: 0/0.
- AI=false, breaker=true, payments=disabled, live payments=false on the deployed
  API and workers. Provider keys remain empty; application networks remain internal.
- Windows reviewer VPN requests with normal certificate validation: liveness and
  readiness 200, exact frontend CORS, anonymous identity/preview 401, docs 404.
  Public server ports 18443, 18444, 5432 and 6379 remain unreachable.
- Vercel protection remains `deploymentType=all`, with no bypass credentials.
  Signed-out custom, new and prior deployment URLs redirect to Vercel authentication.
- Vercel frozen install, webpack build, TypeScript and static page generation passed.
  Frontend regression run: 77 passed, zero failures/skips. The earlier concurrent
  run exhausted local memory; the completed run was sequential.
- Resumed backend release regressions: 3 passed with isolated PostgreSQL and real
  FFmpeg; minimum-price/economics checks: 6 passed. Earlier broad report contained
  206 passing cases and two corrected release-test failures; this is not reported
  as a fresh broad-suite pass. Ruff and mypy passed.
- The short and two-minute synthetic sources produced captioned, playable 20-second
  720×1280 H.264/AAC MP4s with full decode and audio/video timing checks. These used
  mocked AI providers. Saved desktop/mobile browser tests from the earlier execution
  passed upload, quoted generation, video playback, private MP4 download, insufficient
  credits and navigation. The resumed browser run was interrupted and did not pass.

No connected browser surface was available for a fresh signed-in protected staging
test. Authenticated staging upload/quote navigation needs the owner's signed-in
browser. HTTP and server-side service checks are not claimed as browser verification.
Live AI processing remains unverified and intentionally disabled. No production
readiness or measured profitability claim is made. Scanner findings match the
existing approved private baseline: 1 critical / 212 high; no new findings or
available fixes in the retained scanner data were introduced by this code release.

## Backup and recovery

Completed quiesced backup: `20261016T192534-00543237.json`, manifest SHA-256
`dc3e71f1779600ab7db275ee98411d0fc9203bd68e4def1dd2f15c8174e04357`.
Both encrypted payloads and the manifest were copied into the existing protected
local backup directory and hash-verified. Local age decryption authenticated EOF
for both payloads; pg_restore validated the dump archive listing, and streaming
media inspection found the exact existing video hash. No plaintext media was
extracted, no existing database was restored/modified, and the recovery identity
never left this PC. Earlier full empty-target restore evidence remains preserved.

Old images/releases, encrypted backups and pre-rollout environment/unit/approval
metadata remain retained. The post-rollout catalog uses `minimum_job_credits`,
which the old image's strict rules schema cannot parse: do not blindly switch to
the old quote-fix image after catalog installation. A rollback must first append
audited compatible terms under closed controls, or use a reviewed compatible image.
Do not delete immutable price history or restore over the existing database.

Ignored execution receipts, source manifests, deployment/build logs, security
checks and backup authentication results are under
`var/deployment-execution/resume-20261017/`. Media/browser test evidence remains
under `var/release-evidence/`. Neither directory is uploaded to Vercel or Git.
