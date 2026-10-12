# Phase 8, Milestone 2 — real workspace and credits

Date: 2026-10-13 (Asia/Karachi). The user authorized only workspace and credit
read integration. Milestone 1 is preserved. Uploads, processing, editing, payments,
admin integration and subsequent milestones remain outside this implementation.
During implementation, no deployment, VPS changes, commit or push was performed.
The user subsequently authorized separate Milestone 2 commits and normal pushes
to the existing GitHub origins. That publication does not authorize deployment.

## Starting state and scope

Both repositories were clean on `main`, matching their recorded `origin/main`:
backend `9d9cea0bf071396f7579fe351ac5057886878695` and frontend
`f8accb9989ade6df37e05c5aeb1b37814b9bb419`. The user reports M1 was pushed.
No fetch, reset, history rewrite, staging, commit or push was needed/performed.
Backend guardrails, master specification, Phase 8 prompt, architecture, status,
OpenAPI and frontend authentication handoff were reviewed before implementation.

All required reads already existed. No backend application behavior, endpoint,
response schema or migration changed. Backend changes are isolated test fixtures,
contract tests, an opt-in disposable browser-fixture helper and this status/handoff.

## Implemented frontend behavior

- Authenticated profile remains sourced from GET `/api/v1/me`. Read-only Account
  displays the actual email, verification, role, creation date and account ID.
- Overview and Videos/Jobs/Clips read the existing owner-scoped listings, with
  their exact `before` pagination contract. Jobs show real stage/state/update,
  attempts, estimated credits and nullable progress. Clips show saved preferences
  and revision, without claiming successful render/export/playback.
- Credits shows actual available/reserved balances, ledger deltas/after-balances,
  entitlements and plan catalog. Ledger uses authoritative `next_cursor`;
  entitlements use UUID `cursor`. Exact price versions determine plan labels.
  Null pricing is unconfigured; no plan, grant or price is fabricated. PKR paisa
  uses integer arithmetic, with safe-integer response checks.
- Fabricated authenticated dashboard clips, statistics, fixed date, balances,
  service health and fake editor/project actions are removed. Overview counts
  explicitly mean loaded records, not all-time totals. Job updates replace fake
  activity. Unsupported functionality is absent, disabled or explicitly labeled.
- Each resource has loading, empty, error, retry, refresh and load-more handling.
  Page errors preserve loaded records; refresh clears stale data. A failed wallet
  never becomes a zero balance. Responsive navigation and the premium palette,
  cards, spacing and typography remain. Long email addresses do not size headings.
- Workspace data is local to each authenticated account mount. Revalidation
  hides/disposes account resources; logout/account changes abort reads and ignore
  delayed responses. Any active workspace 401 immediately hides data and shows
  expiry. Cross-tab changes revalidate identity. The selected section survives
  same-account revalidation; logout clears it. Cookies/CSRF stay as in M1.
- Generated types, response validators and endpoint/cursor descriptors are
  derived from the existing OpenAPI snapshot. `api:check` verifies both contracts.
  Added pinned Node-compatible lint tooling and warning-free React/Next/a11y checks.

See [`frontend/WORKSPACE_INTEGRATION.md`](../../frontend/WORKSPACE_INTEGRATION.md)
for exact contract/display rules and reproducible browser commands.

## Files changed

Frontend (18 files):

- UI: `components/workspace-view.tsx`, `components/zoclip-app.tsx`,
  `components/auth-view.tsx` (explicit accessible input labels).
- Client/state/contracts: `lib/workspace-api.ts`, `lib/workspace-resource.ts`,
  `lib/use-workspace.ts`, `lib/workspace-schema.ts`, `lib/auth-api.ts`,
  `lib/use-auth.ts`, `scripts/generate-workspace-api.mjs`.
- Tests: `tests/workspace-api.test.mjs`, `tests/browser/workspace.spec.ts`,
  `tests/browser/auth.spec.ts` (real empty account assertions).
- Tooling: `package.json`, `pnpm-lock.yaml`, `next.config.mjs`.
- Handoff: `AUTH_INTEGRATION.md`, `WORKSPACE_INTEGRATION.md`.

Backend (5 files): `tests/workspace_fixture.py`, `tests/test_workspace_api.py`,
`scripts/seed_workspace_test.py`, `docs/IMPLEMENTATION_STATUS.md`,
`docs/PHASE8_WORKSPACE_MILESTONE.md`. Existing application source, migrations,
OpenAPI snapshot, configuration secrets and data are unchanged.

## Verification evidence

| Check | Result |
|---|---|
| Frontend unit tests | PASS: 21 (11 preserved auth, 10 workspace) |
| Generated contract drift | PASS: auth and workspace match backend OpenAPI |
| TypeScript | PASS: standalone and production build |
| Frontend lint | PASS: React, Next.js, accessibility and TypeScript correctness; zero warnings/errors |
| Production build | PASS: optimized Turbopack compile, TypeScript, all static routes |
| Chrome suite | PASS: 11 (5 auth, 6 workspace), including real backend identity/data/session flows |
| Desktop/mobile review | Workspace-only screenshots reviewed; fixture account data only; mobile navigation and overflow assertions pass |
| Backend focused tests | PASS: 63, zero failures/skips; real separate disposable PostgreSQL/Redis |
| Backend lint/type | PASS: Ruff and mypy (70 source files) |
| Backend OpenAPI validity/export match | PASS as part of focused config tests; application API unchanged |

The backend command was:

```powershell
# Read only the new harness's private state into variables; never print it.
$testState=Get-Content 'var/phase8-auth/<run-id>/state.json' -Raw | ConvertFrom-Json
$env:TEST_DATABASE_URL=$testState.test_database_url
$env:TEST_REDIS_URL=$testState.test_redis_url
.venv/Scripts/python.exe -m pytest tests/test_workspace_api.py tests/test_auth.py tests/test_google.py tests/test_config.py tests/test_infrastructure.py tests/test_credits.py::test_customer_api_is_scoped_strict_and_cannot_grant tests/test_credits.py::test_staff_api_audited_idempotent_and_pagination tests/test_credits.py::test_unconfigured_catalog_and_anonymous_balance -q --basetemp 'var/phase8-auth/<run-id>/pytest-m2'
```

New backend coverage checks anonymous denial on every private read; two-account
isolation; all listing pagination; foreign media cursors; invalid bounds/cursors;
retention filtering; response serialization without private job payloads; wallet
versus ledger reconciliation; entitlement pagination/current/future status; and
configured/unconfigured catalog contracts. Existing auth/security/config/RQ and
credit permission/pagination regressions remain included.

Chrome uses actual local FastAPI reads and synthetic DB fixtures for distinct
accounts (21 retained Alice videos/clips, 23 jobs, 42 transactions, 21 entitlements;
one Bob video/job/clip with a distinct balance). Separate controlled responses
test pending requests, API 503/retry and malformed wallet handling. M1 registration
also verifies a real fresh account's zero balance and empty lists. Real logout,
reload, cross-tab switching and externally revoked sessions are exercised.
These are explicit test fixtures, never production fallback data. No actual media
processing or credit/payment API writes are enabled in the workspace UI.

## Tooling issues encountered

The C: drive was full and virtual memory was initially nearly exhausted. An npm
command failed with ENOSPC, and an initial production build/Python run failed to
allocate memory. No system/user data was deleted and unrelated apps were not
stopped. TEMP/TMP/npm caches were redirected into ignored workspace directories;
our temporary servers were stopped before building. The user was asked to close
unused apps. A one-worker opt-in `ZOCLIP_LOW_MEMORY=1` configuration, bounded Node
heap and `RAYON_NUM_THREADS=1` allowed the full build to pass with type checks intact.

The first selected linter required newer Node and its optional binary was skipped.
It was replaced by exact Oxlint 1.0.0, compatible with installed Node 20.18. No app
dependency changed. The first fixture seeding attempt lacked registration of a
nullable ORM foreign-key target; that transaction rolled back, the test-only import
was added, and successful seeding followed. An initial mobile browser helper
targeted the desktop-only sign-in button; the helper now uses the visible mobile
entry. Final checks passed after these corrections. Existing FastAPI/Authlib test
dependency deprecation warnings remain; no unrelated dependency upgrade was made.
Final file review found no added live secrets or generated/private artifacts among
the changes. Historical credential URLs in implementation status were confirmed
to be unchanged test placeholders. New fixture state, screenshots, service data,
temporary caches and test output remain ignored. At the implementation gate both
histories remained at the M1 commits. The subsequent publication review confirmed
exactly the 18 frontend and 5 backend milestone files, no unrelated changes, valid
generated contracts and passing lint; both origins matched local history before
the separately authorized commits and normal pushes.

## Data and remaining boundaries

Every harness start created a new unique PostgreSQL data directory and separate
browser/backend `_test` databases. The existing API on 8000, existing PostgreSQL
and Docker services/data were left untouched. Test migrations/downgrade/Redis
cleanup targeted only the new separate disposable backend test DB and Redis 15.
All new evidence/data is preserved in ignored `var/phase8-auth/<run-id>`; only our
temporary service processes were stopped after verification.

No Milestone 2 API blocker remains. Real accounts can legitimately have no media,
zero credits, no entitlements or unconfigured prices. Catalog administration,
email delivery and production configuration retain their earlier launch gates;
this milestone does not authorize those changes. Aggregate totals/activity APIs
are absent, so the UI labels loaded counts and displays actual job snapshots.
Uploads, processing, editing, payments and admin integration await later milestones.
The full Linux paid-provider/media/render/payment regression was not rerun for
this frontend-only behavior change. No production readiness or deployment claim.
