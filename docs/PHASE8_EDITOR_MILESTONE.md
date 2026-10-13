# Phase 8, Milestone 4 — AI suggestions, editor, captions and exports

Date: 2026-10-13 (Asia/Karachi). **Local mock/fixture integration verified.**
M1–3 are preserved at backend `38865ad1f631e57822bb2fe503b7ed488c2c9ea2`
and frontend `7070d47dfb01768094d95de08542c2d20f91ff8b`.
Both trees were clean before M4. No commit/push, deployment, VPS operation,
billing/admin integration, live provider call or key configuration was performed.

## Implemented

- Actual transcript and suggestions reads, with transcript pinned to the returned
  PROCESS job; stored timestamp/rank/score/hook/reason/hashtags, not fake highlights.
- Candidate-idempotent draft creation and current clip reads. Editor supports
  source-millisecond trims, title/hashtags, caption text and timings, preset/font/
  placement, framing and manual focal coordinates. Complete Preferences are sent
  with quoted If-Match; conflicts/uncertain saves retain local edits until explicit
  server reload/reconciliation, without automatic overwrites or replay.
- Caption enums come from OpenAPI: classic/bold/karaoke, the three supported
  fonts, bottom/middle/top, and track/center/pad/manual. Only implemented 9:16,
  720×1280, H.264/AAC MP4 is offered. No fake local caption/face-tracking preview.
- Explicit fixed-selection render approval against the original credit estimate.
  Confirmed selection/key survives ambiguous responses. Existing pipeline/RQ
  renders actual MP4s; nullable progress, job states/errors/events/cancel remain
  authoritative. A suggestion or individual COMPLETE output is not presented as
  a completed deliverable before its entire associated job completes.
- Saved-revision re-render with prepaid edit allowance first; optional fresh
  source-based quote and explicit credit confirmation. M3's quote form now accepts
  a desired prepaid re-export count. Confirmed revision/quote/key persists for
  recovery; definitive rejections permit correction. No duplicate credit holds.
- Actual revision/output records, private cookie-authenticated MP4 fetches,
  explicit revision downloads and playback of only the received MP4. Preview
  identifies its downloaded revision; unsaved edits never masquerade as rendered.
  Temporary Blob URLs are revoked on replacement/account disposal. Download MIME
  and the backend's hard 512 MiB ceiling are enforced; fallback buffering remains
  bounded by that ceiling. Browser save completion is not claimed.
- Quota, insufficient-credit, revision/feature/busy/expiry/network errors and
  authentication/account isolation. Existing premium cards/colors/navigation and
  mobile layout are retained. Old editor/export-unavailable states are replaced.

See [frontend integration/recovery](../../frontend/EDITOR_INTEGRATION.md) and
[exact live-key preparation and controlled plan](PHASE8_LIVE_AI_PLAN.md).

## Verification

| Check | Actual result |
|---|---|
| Frontend units | **38 passed**, zero failures/skips; includes six M4 cases |
| TypeScript / lint / generated contracts | PASS; zero lint warnings/errors |
| Production build | PASS: optimized Turbopack, TypeScript and five generated static pages |
| M3+M4 Chrome run | **10 passed**, including real FFmpeg/private MP4 and three M4 workflows |
| Separate M1/M2 Chrome regression | **11 passed**, existing auth/workspace/account/mobile behavior |
| Backend focused contracts | **105 passed**, zero failures/skips, 200.95s |
| Disposable-capacity boundary tests | **4 passed**, zero failures/skips |
| Backend Ruff/format/mypy | PASS, 122 Python files formatted and 70 application sources typed |
| Live OpenAPI | PASS: running disposable API validates and exactly matches unchanged 56-path snapshot |
| Whitespace / artifact review | PASS; private environments/data/output/caches excluded |

Production build passed with existing D:-local TEMP/TMP/npm cache paths,
ZOCLIP_LOW_MEMORY=1, RAYON_NUM_THREADS=1 and
NODE_OPTIONS=--max-old-space-size=512 --max-semi-space-size=4. The build-only
NEXT_PUBLIC_API_ORIGIN=https://api.zoclip.example is a placeholder, not a deployment.

Backend focused command:

```powershell
# Load only the new harness's private state into variables; never print it.
$s=Get-Content var/phase8-auth/<run-id>/state.json -Raw | ConvertFrom-Json
$env:TEST_DATABASE_URL=$s.test_database_url
$env:TEST_REDIS_URL=$s.test_redis_url
$env:FFPROBE_BINARY='<existing-local-ffmpeg-bin>/ffprobe.exe'
$env:FFMPEG_BINARY='<existing-local-ffmpeg-bin>/ffmpeg.exe'
.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_ai.py tests/test_rendering.py tests/test_phase8_editor_api.py -q --tb=short --basetemp=var/phase8-m4/contracts-tmp -p no:cacheprovider --junitxml=var/phase8-m4/contracts.xml
.venv/Scripts/python.exe -m pytest tests/test_editor_browser_fixture.py -q -p no:cacheprovider
```

New HTTP integration coverage: real transcript/suggestions, unavailable export
before render, verified MP4/dimensions, correct/stale If-Match, current-unrendered
versus historical completed downloads, foreign transcript/clip/output/download/
edit/render/selection denial, unsupported preset/aspect/format rejection, invalid
timed captions and missing CSRF/revision headers. Existing AI/render cases include
mock provider failures, FFmpeg failures/recovery/cancel, quotas, duplicate workers,
financial settlement, seek/audio/caption checks and deletion. The four fixture
guards reject production, enabled AI, foreign DB and out-of-harness media roots.
Two existing Authlib/Starlette HTTPX deprecation warnings remain.

Frontend: npm test, api:check, typecheck and lint. Browser commands:
`npx playwright test editor.spec.ts media.spec.ts` in the M4 harness and
`npx playwright test auth.spec.ts workspace.spec.ts` in a separate M2 harness.
Browser tests cover real highlights/transcript/drafts, trim/classic captions/word
edits, initial render settlement, private MP4 download/preview, prepaid rerender,
stale edits retaining local text, fresh paid-export quotation without a debit,
explicit confirmation, lost-response recovery, malformed trim, quota and 401.
Mobile overflow assertions pass at 390×844. No claim of live provider quality.

## Local disk/test boundary

The initial normal-capacity browser run correctly rejected uploads: D: had less
than the configured 20 GiB floor plus the source reservation. No existing data
was deleted to bypass it and no production admission limit was reduced.
Functional M4 browser verification uses an explicit disposable synthetic-capacity
API/worker, real DB/files/outbox/Redis/RQ/FFmpeg and 16 MiB test output ceiling.
Its separate script rejects non-disposable configuration, keeps AI disabled in
the API, and checks at least 1 GiB real free space for the tiny fixtures. Production
application sources and capacity logic are unchanged. This is **not** real-capacity
acceptance; that gate remains blocked on sufficient actual storage.

AI responses come only from the existing test Simulator. Imports in M3 regression
retain the existing synthetic transport. These adapters are not exposed by an
application endpoint. Backend provider env names/REST implementations were reviewed
first; current official key/version/REST docs were checked for the live plan.
Gemini schema fields include deprecation guidance, and compatibility with a chosen
live model remains unverified. No paid request was sent.

Earlier failures are superseded, not counted as passes: real disk admission,
accessible select-label mismatch, and a punctuation encoding issue in updated
guidance. Final combined browser/contract runs above pass. No skipped/failing final
test remains. Full Linux/payment/operations suites, representative throughput and
subjective live-quality/Unicode/face QA were not rerun or inferred.

Evidence/data remain ignored under `backend/var/phase8-m4/contracts.xml` and
the new `backend/var/phase8-auth/` runs:
`694513cbc36340b98314f8fd96621732` (normal-capacity backend checks),
`795b1f1c92364e25946618751ee4ff92` (explicit synthetic-capacity browser checks),
`d27966eada3f46498c33eabef101152a` (auth/workspace regression).
Each harness creates separate PostgreSQL directories and test databases; existing
services/data and Git history are preserved. Synthetic source cleanup preserves
financial/job history. Temporary services are stopped at handoff; data remains.

## Changed files and remaining gates

Frontend (15): `components/clip-workbench.tsx`, `components/workspace-view.tsx`,
`components/media-studio.tsx`; `lib/clip-editor.ts`, `lib/media-api.ts`,
`lib/media-schema.ts`; `scripts/generate-media-api.mjs`, `package.json`;
`tests/clip-editor.test.mjs`, `tests/browser/editor.spec.ts`,
`tests/browser/media.spec.ts`; `EDITOR_INTEGRATION.md`, `AUTH_INTEGRATION.md`,
`MEDIA_INTEGRATION.md`, `WORKSPACE_INTEGRATION.md`.

Backend (11): `scripts/auth_dev.py`, `scripts/media_browser_fixture.py`,
`scripts/editor_browser_api.py`; `tests/test_phase8_editor_api.py`,
`tests/test_editor_browser_fixture.py`; docs `PHASE8_EDITOR_MILESTONE.md`,
`PHASE8_LIVE_AI_PLAN.md`, `IMPLEMENTATION_STATUS.md`, `API_HANDOFF.md`,
`ARCHITECTURE.md`, `DECISIONS.md`.

No application migration/endpoint/schema/provider/dependency/config-secret change.
Required manual gates: sufficient real disk for capacity acceptance; approved
live provider keys/models/version/rates/budgets and compatibility; legal/privacy
and quality/speed measurement; representative long-video/mobile-download memory
and multilingual/face QA; production origins/email/operations/deployment acceptance.
The live plan specifies safe offline key-presence checks with AI_ENABLED=false
and requires explicit approval before enabling AI or running one small paid job.
No billing/admin integration, VPS change, deployment, commit or push is included.
Stop after M4 for user review.
