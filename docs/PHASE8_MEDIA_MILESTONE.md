# Phase 8, Milestone 3 — video uploads and AI processing

Date: 2026-10-13 (Asia/Karachi). **Local mock/fixture integration gate PASS.**
Only M3 was implemented. No commit, push, deployment, VPS change, paid provider
call, billing/admin UI, clip editor or render-selection workflow was performed.
Starting commits remain backend `6c487796dbfd1dcba02685ce249b0ed0e4c169f8`
and frontend `4086ea85312f08c65892658189b6e3d1cd70ac0d`. Both trees started clean.

## Implemented behavior

- Real file initiation, exact-size/checksummed chunk PUTs, server receipt-based
  resume, async completion and upload cancellation. Incremental SHA-256 reads
  1 MiB blocks; one backend-sized Blob part is submitted at a time. Progress
  distinguishes checksum bytes from server-confirmed upload bytes.
- Bounded retries/backoff/jitter, pause, reload/reselection recovery and persisted
  initiation/completion keys. Changed file hashes fail before resumed requests.
  Definitive admission rejection discards local intent. Native picker reset
  permits the same file to be selected after completion/cancellation.
- Direct HTTPS imports with rights attestation and explicit byte ceiling.
  Backend exact-host allowlist and SSRF/redirect/TLS/media checks remain
  authoritative. YouTube/Vimeo/Drive page imports are not offered.
- Authoritative READY source duration → real quote → displayed options/credits/
  expiry → explicit confirmation → existing generation/reservation/outbox.
  Confirmed request persistence recovers lost acknowledgments after reload
  without duplicate holds. A quote alone reserves zero credits.
- Selected-job polling, actual state/stage/nullable progress/heartbeat/attempts,
  recent events, outage recovery and cancellation. WAITING_ENGINE and
  SUGGESTIONS_READY remain intermediate states with accurate copy, not rendered
  success. No processing percentage or queue position is invented.
- Actionable credit/upload/plan/queue/storage/expiry/integrity/URL/network errors.
  New processing attempts require a fresh quote/confirmation; uncertain confirmed
  requests retain the original key and approval.
- Existing cookie authentication, serialized in-memory CSRF and server ownership.
  Account disposal aborts media IO. Background identity checks preserve active
  transfers after a timer tick or native picker focus; failures and explicit/
  cross-tab revalidation still fail closed. Premium styling/navigation remain.

Contract/recovery details and reproducible local commands:
[frontend/MEDIA_INTEGRATION.md](../../frontend/MEDIA_INTEGRATION.md).

## Files changed

Frontend (17):

- `components/media-studio.tsx`, `components/workspace-view.tsx`.
- `lib/media-api.ts`, `lib/media-schema.ts`, `lib/file-hash.ts`,
  `lib/resumable-upload.ts`, `lib/auth-api.ts`, `lib/use-auth.ts`,
  `lib/workspace-api.ts`.
- `scripts/generate-media-api.mjs`, `package.json`.
- `tests/media-api.test.mjs`, `tests/browser/media.spec.ts`,
  `tests/browser/auth.spec.ts` (obsolete M2-only text assertion).
- `MEDIA_INTEGRATION.md`, `AUTH_INTEGRATION.md`, `WORKSPACE_INTEGRATION.md`.

Backend (8): `scripts/auth_dev.py`, `scripts/media_browser_fixture.py`,
`tests/test_phase8_media_api.py`, and docs `PHASE8_MEDIA_MILESTONE.md`,
`IMPLEMENTATION_STATUS.md`, `API_HANDOFF.md`, `ARCHITECTURE.md`, `DECISIONS.md`.
Application sources, migrations, schema snapshot, dependency locks and production
configuration are unchanged. Optional `--media-test-mode` affects only the opt-in
disposable harness; no new application environment variable is added.

## Final verification

| Check | Actual result |
|---|---|
| Frontend unit tests | **32 passed**, zero failed/skipped: 11 auth, 10 workspace, 11 media |
| Generated-contract drift | PASS: auth/workspace/media derive from backend OpenAPI |
| TypeScript | PASS standalone and production build |
| Frontend lint | PASS: zero errors/warnings |
| Production build | PASS Turbopack optimization, TypeScript and five generated static pages |
| Existing Chrome regression | **11 passed** in separate M2-seeded harness |
| M3 Chrome workflows | **7 passed**, zero failed; actual API/outbox/Redis/RQ/FFmpeg with simulated AI |
| Focused backend contracts | **146 passed, 1 skipped**, zero failed; 200.86 seconds |
| Backend Ruff/format/mypy | PASS: 119 Python files formatted; 70 application sources type-check |
| Live OpenAPI | PASS: running schema validates and equals snapshot exactly, **56 paths** |
| Repository whitespace | PASS in both repositories |

Backend command, using the new harness's separate private test DB and Redis 15:

```powershell
$s=Get-Content var/phase8-auth/<run-id>/state.json -Raw | ConvertFrom-Json
$env:TEST_DATABASE_URL=$s.test_database_url
$env:TEST_REDIS_URL=$s.test_redis_url
$env:FFPROBE_BINARY='<existing-local-ffmpeg-bin>/ffprobe.exe'
$env:FFMPEG_BINARY='<existing-local-ffmpeg-bin>/ffmpeg.exe'
.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_media.py tests/test_ai.py tests/test_workspace_api.py tests/test_phase8_media_api.py -q --tb=short --basetemp=var/phase8-m3/contracts-final-tmp -p no:cacheprovider --junitxml=var/phase8-m3/contracts-final.xml
```

The skip is the existing Windows symlink/path test requiring OS privilege;
previous Linux verification covers it. Two existing Authlib/Starlette HTTPX
deprecation warnings remain. Full Linux/render/payment/operations suites were
not rerun for this frontend integration; backend application code is unchanged.
Four new HTTP tests cover upload/resume/duplicate completion, ffprobe, quote
versus confirmed hold, duplicate generation, real extracted audio with the
existing Simulator, events, cancellation/release, foreign operations, rights/
HTTPS/allowlist/limits, unauthenticated mutation and quote expiry.

Frontend commands: `npm test`, `npm run api:check`, `npm run typecheck`,
`npm run lint`, and separate browser commands
`npx playwright test auth.spec.ts workspace.spec.ts` (M2 fixture) and
`npx playwright test media.spec.ts` (M3 fixture). Production build used existing
D:-local TEMP/TMP/npm cache, `ZOCLIP_LOW_MEMORY=1`, `RAYON_NUM_THREADS=1`,
`NODE_OPTIONS=--max-old-space-size=512 --max-semi-space-size=4` and build-only
`NEXT_PUBLIC_API_ORIGIN=https://api.zoclip.example`. This placeholder is not a
deployment configuration or a configured production API.

## Browser coverage and evidence boundaries

The seven M3 cases verify:

1. Real upload/ffprobe, no quote charge, explicit reservation, dropped generation
   acknowledgment, reload/same-key recovery, simulated AI to SUGGESTIONS_READY,
   events, cancellation and restored wallet.
2. Three failed part requests, reload, checksum mismatch rejection, skipped
   confirmed parts, account switching and foreign resource denial.
3. Rights-required import, real allowlist rejection of platform/private URLs,
   and accepted synthetic direct URL reaching validated source completion.
4. Invalid imported media reaching actual FAILED/invalid_media.
5. Zero-credit confirmation rejection without a hold; no mobile overflow at 390×844.
6. Pause/server cancellation, actionable 413, discarded rejected initiation and
   expired-quote review requirement.
7. Polling outage, explicit recovery and 401 clearing visible private data.

Import transport is **synthetic and test-only**, not public HTTPS. Existing
focused backend tests cover production SSRF/DNS/redirect/TLS separately. Existing
AI Simulator replaces providers only in tests/the explicit disposable script;
no application route can select it. Real outbox/RQ workers and maintenance are
used. No Gemini, Deepgram or public origin was contacted.

Earlier failed attempts are superseded, not counted as passes: restricted Windows
test process/temp access; missing pytest parent directory; obsolete empty-state
assertion; attempted mutation of an append-only quote fixture; test-worker Redis/
FFmpeg configuration; oversized synthetic import reservations for local headroom;
native file-picker reset defect; and one-response outage consumed by development
double mount. Corrected final runs above are the acceptance evidence. The real
20 GiB headroom was never lowered. Tiny imported fixtures use a 1 MiB ceiling.

Evidence/data remain ignored on D: under
`backend/var/phase8-auth/{4174bff9961f49b08392ddb9c3c03530,87fd748e5d3346f2b83ad5b8a239b722}`
and `backend/var/phase8-m3`. Each harness used a new PostgreSQL directory and
separate browser/backend test databases. Existing services/data were untouched.
Synthetic source cleanup preserves financial/job history. Temporary service
processes were stopped after checking; data directories were preserved.

## Remaining gates and manual steps

No local M3 implementation blocker remains. Live AI credentials/models/rates/
budgets/quality still need separate approval. Public media-origin verification,
approved plan/credit policy, subprocessor/legal terms, representative 4 GiB/
120-minute/throughput tests, reviewed same-site HTTPS origins/email configuration
and operations/deployment acceptance remain unverified. Empty import allowlists
and unconfigured plans/budgets fail honestly. Browser storage is required for
durable recovery; clearing it or moving browsers needs manual source/job discovery.
Null processing progress and queue position remain unavailable.

M3 ends at processing suggestions. Render selection/editor, billing/admin and
Milestones 4–6 need separate authorization. Stop for review; do not commit, push
or deploy without the user's approval.
