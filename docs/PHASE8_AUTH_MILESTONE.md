# Phase 8, Milestone 1 — outage recovery and authentication

Date: 2026-10-13 (Asia/Karachi). **Local Milestone 1 gate: PASS.** This is the
user-authorized frontend authentication integration, overriding the original
PROMPT 8's documentation-only scope for this milestone. Milestones 2–6, deployment,
VPS changes, commits and pushes were not authorized or performed.

## State recovered before implementation

- Backend: `main`, HEAD `b47fa9c`, matching its recorded origin/main reference.
  Tracked files were clean. Untracked `scripts/auth_dev.py` and
  `scripts/setup_local.ps1` survived. Prior authentication is committed in
  `b551c61` and remains in the current Phase 7 implementation.
- Frontend: `main`, HEAD `3c3a481`, matching its recorded origin/main reference.
  Uncommitted changes survived in `.gitignore`, `app/page.tsx`,
  `components/zoclip-app.tsx`, `next.config.mjs`, `package.json`, `pnpm-lock.yaml`.
  New auth forms, API client/types, session hook, verification/reset routes,
  generator, API tests and `.env.example` also survived. Nothing was staged.
- No interrupted/truncated source file was found. Saved auth code was substantial
  but lacked completed browser coverage and fresh execution evidence. The new
  native service script failed formatting/lint, and its fixed API port conflicted
  with an existing service.
- Current `.venv/pyvenv.cfg` already referenced the correct moved local Python
  3.12.15 path. Imports resolve to this workspace. The preserved older
  `.tools/venv-before-phase8/pyvenv.cfg` still references `D:\zoclip`; it was not
  reused or removed. Frozen offline uv synchronization checks 73 packages.
- Node 20.18.0, npm 10.8.2, project-local pnpm 12.3.4 and the pinned dependency
  cache were present. TypeScript/package resolution initially worked. A frozen
  pnpm verification attempted module replacement and failed with access denied,
  leaving package shims missing. The remaining module directory was moved intact
  to ignored `.tools/node_modules-outage-recovery`; 346 locked packages were then
  copied successfully from the existing cache. No source or lockfile was discarded.
- Docker 29.8.2, Compose 5.5.1 and the Linux engine are available outside the
  sandbox. Existing Phase 1/3/4 verification containers and PostgreSQL/Redis are
  running. An existing API occupies port 8000, and installed PostgreSQL occupies
  5432. All were left untouched. Sandbox Docker access was denied; normal local
  inspection confirmed engine availability.

## Milestone task recovery

| Task | Before resumption | Final result |
|---|---|---|
| FastAPI register/verify/login/logout/forgot/reset/me | Already committed, tested historically | Preserved; fresh focused PostgreSQL/Redis checks pass |
| Typed frontend auth client and generated contract | Saved, implemented but unverified after outage | Preserved, contract drift check passes; runtime success-response guards added |
| Auth forms and token pages | Saved, implemented but unverified after outage | Real browser lifecycle passes, including confirmation/errors and fragment removal |
| Cookie/CSRF integration and fake-login replacement | Saved implementation | Credentialed fetch, CSRF bootstrap/rotation and real server login verified |
| Protected workspace and expiry handling | Saved implementation with a return-home defect | Fail-closed checks, cross-tab changes and revocation verified; return-home fixed |
| Loading/validation/API errors | Saved implementation and 10 client tests | Preserved; malformed success, pending controls, safe errors verified; 11 unit tests |
| Browser test harness/coverage | Dependency/script saved; config/specs not started | Config and five focused Chrome tests implemented and passing |
| Local tooling and documentation | Partial scripts; no recovery handoff | Repaired/preserved; run instructions and evidence recorded |

## Changes completed now

- Repaired native service formatting, added configurable API port and explicit
  test-only rate-limit override with bounded validation. Defaults remain unchanged.
  Unexpected service exits fail clearly. It creates unique private data directories
  and separate browser/backend test databases; it never opens existing data.
- Completed the locked frontend dependency installation from its existing local
  cache. Retained the prior dependency remnants and old Python environment.
- Added runtime checks for `/me`, login, CSRF and message success payloads, so
  malformed 2xx responses cannot establish identity or falsely report success.
- Fixed returning home after session expiry. Replaced the template greeting's
  fake person with the authenticated email name; kept the visual design and the
  clearly labeled remaining workspace previews.
- Exposed the existing `Retry-After` response header through CORS alongside
  `X-Request-ID`. Browser testing found that its absence hid the retry interval.
  Added an assertion on a real backend 429 response. No endpoint/schema/migration
  change was needed.
- Added Chrome coverage for actual registration, verification, wrong/correct login,
  reload/session restoration, cookie protections, logout across tabs, recovery,
  reset with old-password rejection, external revocation, expired-session exit,
  anonymous/Origin/CSRF denial and invalid tokens. Controlled network cases cover
  outages, malformed identity, pending controls, rate limits and CSRF errors.
  Test artifacts do not capture page snapshots, screenshots, video or traces.
- Added frontend `AUTH_INTEGRATION.md` with setup, private mailbox, contracts,
  verification commands and deployment configuration requirements. Expanded frontend
  environment-file ignores. Next.js generated its agent guidance and type-reference
  file during startup; these were inspected and preserved.

## Actual verification

| Check | Final outcome |
|---|---|
| Frozen offline backend setup | PASS; 73 packages checked |
| Frozen offline pnpm cache install | PASS; 346 packages copied; lock unchanged from recovery |
| `npm test` | PASS; 11 tests, zero failures/skips |
| `npm run api:check` | PASS; generated auth contract exactly matches backend snapshot |
| `npm run typecheck` | PASS; no suppressed errors |
| `npm run build` | PASS; optimized build, TypeScript and static generation for `/`, `/verify-email`, `/reset-password` |
| `npm run test:browser` | PASS; 5 Chrome tests in 15.0 seconds |
| pytest auth/google/config/infrastructure with new TEST_DATABASE_URL and TEST_REDIS_URL | PASS; 49 tests, zero failures/skips, 31.15 seconds |
| `ruff check src tests scripts alembic` | PASS |
| `ruff format --check src tests scripts alembic` | PASS; 114 files |
| `mypy src` | PASS; 70 source files |
| Actual FastAPI OpenAPI validation and equality to docs/openapi.json | PASS; no schema drift |
| `git diff --check` in both repositories | PASS |

Backend evidence is private/ignored at
`var/phase8-auth/c460cedb51254c67ad2cfedb2d87d23e/backend-auth.xml`.
Each test fixture targets only the new disposable backend database; its existing
migration up/down/up/check and Redis database-15 cleanup were never run against
browser data, existing project databases, containers or production.

Earlier attempts are not counted as passes: sandbox Node test execution failed
with spawn EPERM; direct script execution hit Windows execution policy; initial
native lint/format failed; pnpm replacement failed before cached recovery; an
OpenAPI command initially omitted its required schema-only database configuration;
the first browser run needed CommonJS module-loading/selector corrections;
repeated browser bootstraps hit the default auth rate limit; the final browser
iteration exposed the CORS header gap. All were corrected and relevant checks
rerun successfully. Two existing HTTPX/Starlette/Authlib deprecation warnings remain.
An initial backend run skipped Redis smoke; the final run included it and skipped
nothing. No full Phase 2–7 regression, remote CI, benchmark or deployment is claimed.

## Remaining manual/launch requirements

Milestone 1 is complete for local development. The local services use actual
FastAPI/PostgreSQL/Redis and private development-mailbox delivery. They do not
send live email. A production email adapter/durable delivery and approved sender
remain backend launch work; the frontend already handles email-unconfigured 503.
Google remains disabled and is outside this milestone.

Production requires same-site HTTPS app/API origins, secure HttpOnly cookies,
exact CORS/Origin values and the actual public API origin at frontend build time.
The build check used an example HTTPS origin, not deployment configuration.
No secrets were logged or placed in source, and no paid provider/payment was called.
No database reset, existing data deletion, commit, push, deployment or VPS action
was performed. Temporary native auth services and the frontend started for these
checks were stopped afterward; all disposable evidence/data and pre-existing
Docker containers were preserved. Use the frontend handoff for local restart steps; further milestones
require a new user instruction.

## Authorized local checkpoint review

After the local gate was accepted, the user authorized separate backend/frontend
commits, preserving history and withholding push. The review found no unrelated
changes or live credentials in the milestone files. Development credentials are
generated at runtime into ignored private state; committed test passwords/tokens
are synthetic fixtures only. Build output, dependency caches, databases, mailboxes,
test results and local environment files remain ignored and preserved on disk.
Frontend `next-env.d.ts` is ignored as required by the installed Next.js guidance;
the generated OpenAPI-derived auth contract is intentionally versioned with its
generator and drift check. Next.js agent guidance is retained as project tooling.
