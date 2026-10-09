# ZoClip implementation status

Phase 1 foundation is implemented; local PostgreSQL-backed checks are recorded below.
Latest infrastructure verification: 2026-10-10; Docker build/Compose startup,
container PostgreSQL migrations, official Linux Redis and both RQ workers PASS.
All 49 tests pass against Docker PostgreSQL/Redis. See the final verification below;
earlier follow-ups are historical evidence, superseded by this completed local gate.
Phase 2 has not started. At the Phase 0 audit on 2026-10-09, the repository contained only
`docs/ZOCLIP_BACKEND_MASTER_SPEC.md` and `docs/ZOCLIP_CODEX_PHASED_PROMPTS.md`.
There was no AGENTS.md, application, dependency manifest, Compose configuration,
migration, API schema, test suite or frontend. Existing input documents preserved.
No runtime features existed at that audit. Phase 1 now adds application/tests/migrations;
no live provider requests, benchmarks or deployment have been performed.

## Phase gates

| Phase | Status | Completion evidence / required gate |
|---|---|---|
| 0 Repository blueprint | Documentation complete | AGENTS.md, ARCHITECTURE.md, DECISIONS.md and this status; consistency review against complete master spec and PROMPT 0 |
| 1 Foundation/auth | PASS — local development gate verified | Docker build/startup, health, PostgreSQL migrations, Linux Redis/both RQ workers, 49 tests, lint/type/contract checks pass; live Google/email and production remain unverified |
| 2 Ledger/budgets | NOT STARTED | Actual PostgreSQL concurrent spend/idempotency/reconciliation tests, versioned quotes and atomic budget admission |
| 3 Ingestion/queue | NOT STARTED | Real chunk upload/direct allowed URL, SSRF/IDOR/disk tests, durable dispatch/recovery, no AI charges |
| 4 AI suggestions | NOT STARTED | Mock-tested adapters plus opt-in configured real transcription/validated suggestions; rendering still absent |
| 5 Render/editor | NOT STARTED | Actual captioned vertical MP4, revision rerender, isolation and exactly-once settlement; representative QA |
| 6 Payments | NOT STARTED | Verified sandbox credits once; spoof grants zero; merchant live status separately evidenced |
| 7 Operations | NOT STARTED | Compose/runbooks, resource/failure/security drills, encrypted backup restore, monitoring; VPS verification separately recorded |
| 8 Frontend handoff/audit | NOT STARTED | Actual generated validated OpenAPI, samples/v0 prompt, requirement evidence and release blockers; no frontend build |

## Phase 0 deliverables and verification

| Requirement | Evidence | Outcome |
|---|---|---|
| Complete specification and requested prompt read | Master sections A–N; prompt pack PROMPT 0 | Reviewed; future phases are context, not current scope |
| Repository audit | `rg --files`; `git status --short` | Only two input docs; input docs untracked at audit |
| Engineering/security guardrails | `../AGENTS.md` | Documented, not executable enforcement |
| Components, DB/queue/storage/auth/media/money | `ARCHITECTURE.md` | Designed, not implemented |
| Defaults vs unresolved decisions and host risks | `DECISIONS.md`, architecture capacity section | Explicit provisional limits; no benchmark claims |
| Module/dependency/migration/error/API conventions | `ARCHITECTURE.md` | Proposed; dependency versions not resolved |
| Later v0 cookie/CORS integration | `ARCHITECTURE.md` | Planned; frontend outside scope |
| Phase gates and test matrix | This file | Documented |

Commands used: PowerShell `Get-Content ... -Encoding utf8` (master read in complete
sections after initial combined output truncated), `rg --files` and
`git status --short`. Documentation creation used apply_patch. Final verification
used `git diff --check` (exit 0; no tracked diff, so it does not validate the
untracked new documents) and explicit UTF-8 file-content checks (exit 0; all four
new documents nonempty). Manual consistency review covered scope, server limits,
credit/spend/payment invariants, URL policy and future-phase status. `git status
--short` showed untracked `AGENTS.md` and `docs/`; nothing was staged. There is no
test runner to execute in this documentation-only phase.
No generated OpenAPI, `.env.example` or API_HANDOFF is asserted: these accompany
actual Phase 1 routes/configuration rather than fictional scaffolding in Phase 0.
No migrations or environment variables were added. No git commit was created.

## Cross-phase test matrix (Phase 1 outcomes below; later phases unexecuted)

| Phase | Meaningful verification |
|---|---|
| 1 | pytest auth/token expiry/replay/logout/OIDC state, CSRF, brute force, Alice/Bob and staff isolation; PostgreSQL migration up/down; lint/type; generated schema snapshot |
| 2 | Concurrent real PostgreSQL reservations, ten duplicate operations, settle/release race, refunds/adjustments, constraint failures, ledger reconciliation, concurrent budget holds and missing-rate fail-closed |
| 3 | Chunk duplicates/reordering/truncation, path traversal, malicious/overlong real media, DNS rebinding/IPv6/redirect SSRF, 507 and concurrent disk reservations; outbox crash, Redis outage, worker leases/cancel |
| 4 | Mock timeouts/429/5xx/invalid or huge output, timestamp/chunk validation, caching and unknown paid-call recovery, budget exhaustion; explicitly opted-in real provider smoke |
| 5 | Small licensed FFmpeg fixtures -> probed MP4, caption escaping/Unicode/audio sync, fallback crop/manual review, edit conflict, quota and duplicate worker settlement; optional 10/30/60/120-minute benchmark |
| 6 | Forged redirect/signature/mismatched amount grants zero; duplicate/out-of-order/concurrent callbacks grant once; expiry/late event reconciliation, reversal with spent credits, mock production rejection |
| 7 | Disposable mock-only load and DB/Redis/worker/disk/provider/render failure drills, secret/config security checks, restore rehearsal, manual VPS/TLS smoke and measured resource envelope |
| 8 | OpenAPI generated from running routes and validated; contract samples, all requirement PASS/PARTIAL/FAIL evidence, frontend handoff audit and release gate |

Use disposable PostgreSQL/Redis and safe local media, no production data or automatic
paid API load. Distinguish mock integration success from configured real-provider
success and from VPS deployment evidence.

## Phase 1 implementation and evidence

Only Phase 1 was implemented. No wallet, plans, budget engine, payment routes,
uploads, media processing, AI calls, trial grants or frontend were added.

| Deliverable | Files / implementation | Verification |
|---|---|---|
| Package/configuration | pyproject.toml, uv.lock, .env.example, core/config.py | Python 3.12.15 resolved/installed; unsafe configuration tests pass |
| API foundation | main.py, core/db.py, errors.py, rate_limit.py, security.py | Health, structured errors/logging, body limit, CORS/host/security-header tests pass |
| Real PostgreSQL auth schema | auth/models.py; Alembic revision 39bc6d102a49 | Upgrade -> base downgrade -> upgrade -> schema check verified on disposable PostgreSQL 17 |
| Email/password auth | auth/routes.py, schemas.py, service.py | Register/verify/login/logout/reset, invalid/unverified/disabled/expired/replayed token and revocation cases pass |
| Sessions and CSRF | auth/dependencies.py, service.py, core/security.py | Hashed opaque tokens, rotation, secure cookie flags, forged/missing CSRF and Origin rejection verified |
| Ownership and staff authorization | owned_resource/current_user/require_admin; own session detail/admin audit routes | Alice/Bob isolation, role injection rejection, denied staff access and audited authorized reads verified |
| Immutable audit records | auth/models.py; PostgreSQL mutation-rejecting trigger | DELETE rejected by database test; owner/superuser privilege boundary documented |
| Email adapter | auth/email.py | Explicit private development mailbox; disabled email returns 503 without creating accounts; no SMTP/live delivery |
| Google OIDC | auth/google.py | Disabled config, state/browser/expiry/replay, verified-email/linking/revocation tests pass; actual adapter tested with locally RSA-signed tokens and mocked HTTP |
| Concurrency | consume_email_token; PostgreSQL user/token locks | Two separate real DB connections consume a token exactly once |
| Docker/RQ foundation | Dockerfile, compose.yaml, workers/run.py | YAML parses; Windows-port Redis/separate-process RQ smoke verified in follow-up. Docker build/start and Linux worker entrypoints PENDING |
| Contract/docs | scripts/export_openapi.py, docs/openapi.json, AUTH_HANDOFF.md, API_HANDOFF.md, README.md | Generated actual schema validates and matches route snapshot |
| CI | .github/workflows/backend.yml | Configured disposable PostgreSQL/Redis, checks, Docker build, Compose startup and both worker smoke jobs; workflow NOT RUN here |

### Actual commands and outcomes

Windows host initially had no Python/Docker/uv on PATH; an unrelated pgAdmin Python
3.13 was found but not used for project execution. Portable uv 0.12.24 and Python
3.12.15 were downloaded into ignored `.tools`, with `.venv` and cached dependencies.
Restricted-network attempts failed; downloads succeeded after tool approval.
PostgreSQL 17 binaries initialized a separate ignored `.tools/pgdata` cluster bound
to 127.0.0.1:55432. Startup required tool approval; existing installed DB data was
not used. Test database: `zoclip_phase1_test`, disposable data only.

| Command | Actual outcome |
|---|---|
| `uv sync --python 3.12` (workspace-local uv/cache/python) | Installed 71 packages; Python 3.12.15; exact versions/hashes in uv.lock |
| `uv lock --offline` | Resolved 71 packages successfully after manifest changes |
| `alembic revision --autogenerate -m phase1_identity` | Generated revision; reviewed and corrected duplicate OAuth constraint names; added audit immutability trigger |
| `alembic upgrade head` | Passed against disposable PostgreSQL |
| `alembic check` | Passed: No new upgrade operations detected |
| `ruff check src tests scripts alembic` | Passed |
| `ruff format --check src tests scripts alembic` | Passed, 26 files formatted |
| `mypy src` | Passed, 18 source files |
| `python scripts/export_openapi.py` | Generated docs/openapi.json from actual FastAPI routes; no provider/DB connection |
| `pytest -q --tb=short` with TEST_DATABASE_URL | Final post-review run: 48 passed, 1 skipped, 2 warnings in 17.65s |
| PostgreSQL `SHOW timezone` via configured engine | UTC confirmed |
| PyYAML parse of compose.yaml and CI workflow | Passed; DB/Redis port assertions passed (not a Docker validation/build) |
| `git diff --check` and explicit new-source/config whitespace checks | Passed; Git reports LF/CRLF conversion notices only |

At the initial Phase 1 handoff, tests were run using `.venv/Scripts/` executables. That suite used real
PostgreSQL for persistence, not SQLite; local Redis rate tests use explicit
fakeredis + Lua. `test_real_redis_rq_roundtrip` skips because TEST_REDIS_URL is
absent and no Redis/Docker runtime is available. CI is configured to run auth tests
against actual Redis plus the RQ smoke when executed; that result is not claimed.

Verification history: first restricted pytest run had 19 passes/27 temporary-directory
permission setup errors. An accidental DB-test-only invocation without TEST_DATABASE_URL
skipped 17 tests and was not counted as verification. Approved full run reached
43 passes/3 failures caused by a concurrency fixture retaining its test user;
cleanup was fixed. Subsequent runs passed 46 tests, then 48 after adding security
regressions. No known test failure remains. Two warnings concern deprecated HTTPX
fallbacks in installed Starlette/Authlib; not suppressed. Migration tests run a full
up/down/up and schema drift check as part of the suite.

Resolved core versions include FastAPI 0.143.0, Pydantic 2.14.0, SQLAlchemy 2.1.4,
Alembic 1.20.0, psycopg 3.3.6, Redis client 6.4.0, RQ 2.12.0, Authlib 1.8.0,
joserfc 1.7.5, argon2-cffi 25.1.0 and HTTPX 0.28.1. These are observed installed
versions, not guessed minimums or claims about future compatibility. Container
images/tool versions are specified but have not been pulled/built locally.

### Configuration and migration handoff

Revision 39bc6d102a49 creates users, sessions, OAuth identities/flows, email
verification/reset tokens and admin audit logs with indexes, unique and CHECK
constraints. It adds an audit immutability trigger/function. Production runtime
must not have schema-owner/superuser powers; role separation is a remaining
deployment requirement. No financial schema exists.

New settings: APP_ENV, DATABASE_URL, POSTGRES_PASSWORD (Compose bootstrap), REDIS_URL,
PUBLIC_APP_URL, API_PUBLIC_URL, ALLOWED_HOSTS, COOKIE_SECURE, SESSION_TTL_SECONDS,
ANONYMOUS_TTL_SECONDS, AUTH_RATE_LIMIT, AUTH_RATE_WINDOW_SECONDS, EMAIL_MODE,
DEV_MAILBOX_DIR, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI,
PAYMENT_PROVIDER, ENABLE_LIVE_PAYMENTS, ENABLE_TRIAL_CREDITS. The final two are
rejected when enabled; production mock payment mode is rejected. No live values
are committed. Session/CSRF signing secrets are unnecessary with hashed opaque tokens.

Missing/partial Google configuration fails clearly. EMAIL_MODE=disabled makes
registration/recovery unavailable for all users; development mailbox is forbidden
in production. No production email, live Google authentication, Docker deployment,
VPS load or backup/restore success has been asserted. The Windows-port Redis/RQ
follow-up is separate from the pending official Linux container gate.

### Blockers and Phase 2 readiness

Core Phase 1 auth/authorization and PostgreSQL migration checks are verified locally.
Full infrastructure gate remains partial until the supplied Docker build/Compose
and real Redis/RQ CI/manual checks pass. Live Google credentials and real email
delivery are separate launch blockers; disabled behavior is already verified.
Production TLS/proxy setup, least-privilege DB roles, scheduled expired-token cleanup,
retention, backups and restore are not complete. No paid API costs were incurred.

Do not start Phase 2 automatically. Next authorized phase is PROMPT 2 (atomic
ledger, plans, quotes and spending budgets), after required infrastructure checks
and explicit user instruction. Merchant/pricing/domain decisions remain pending
but do not require inventing values for Phase 2 tests. No git commit was created.
Suggested commit: `feat: add PostgreSQL authentication and secure backend foundation`.

## Phase 1 infrastructure follow-up — 2026-10-10

User clarified: Docker is not installed locally; do not connect to or modify Contabo.
Finish non-Docker checks, provide Docker Desktop/WSL2 instructions, keep the Docker
and Linux Redis/RQ gate pending, and do not start Phase 2. All work remained local.
No WSL/Docker installation, OS configuration change or remote server access occurred.

### Exact observed results

| Check / command | Outcome |
|---|---|
| `docker version`, `docker compose version`, `docker build --tag zoclip-phase1 .` | BLOCKED: PowerShell CommandNotFoundException; Docker absent. Build did not execute |
| Standard Docker folders/services and PATH discovery | No Docker installation/daemon found; user confirmed absence |
| `wsl --status` | No usable modern version/status; WSL2 readiness not verified |
| Native PostgreSQL 17.11 at 127.0.0.1:55432 | SELECT 1 returned 1; timezone UTC |
| `alembic upgrade head`, `alembic current`, `alembic check` | Passed; revision 39bc6d102a49 (head); no new upgrade operations |
| Migration fixture in complete pytest run | Upgrade -> downgrade base -> upgrade -> schema drift check passed on zoclip_phase1_test only |
| Local Windows-port Redis 7.4.9 at 127.0.0.1:56379 | PING True; reported MSYS_NT-10.0-19045 OS; NOT the official Linux Docker image |
| `pytest -q --tb=short` with TEST_DATABASE_URL and TEST_REDIS_URL | Final run: **49 passed, 0 failed, 0 skipped, 2 warnings in 21.80s** |
| `test_real_redis_rq_roundtrip` | Passed against real TCP Redis; a separate SimpleWorker process consumed the queued getpid job and returned a PID distinct from the test process |
| Native Uvicorn process at 127.0.0.1:58000 and real HTTP requests | Startup completed; /health/live 200 alive, /health/ready 200 ready, unconfigured Google start 503 google_unconfigured; this is NOT container startup |
| `ruff check src tests scripts alembic` | Passed |
| `ruff format --check src tests scripts alembic` | Passed; 27 Python files |
| `mypy src` | Passed; 18 source files |
| `python scripts/export_openapi.py` / contract test | Regenerated actual schema; validation/snapshot tests passed |
| Python compile of container_smoke.py | Passed; container execution NOT performed |
| PyYAML Compose/CI parsing, `git diff --check` | Passed; parsing is not Docker validation; Git line-ending notices only |

Test environment variables were:

```text
TEST_DATABASE_URL=postgresql+psycopg://zoclip_test@127.0.0.1:55432/zoclip_phase1_test
TEST_REDIS_URL=redis://127.0.0.1:56379/15
```

No live credentials or new application environment variables were added. No schema
changes, new migration or dependency changes were needed in this follow-up.

The test-only Redis archive came from the third-party
[redis-windows 7.4.9 release](https://github.com/redis-windows/redis-windows/releases/tag/7.4.9).
Published SHA256 verified before extraction:
`98AF6511CA35601CC8D8200A92318E00F9D2D5425A9F7F3E8F699D3BDD59DCF6`.
It ran with persistence disabled and loopback binding only, under ignored `.tools`;
no Windows service was installed. This was local supplementary evidence, not a
replacement deployment dependency or verification of the Linux Redis image.
The auth suite used this real Redis for Lua throttling, not fakeredis on this run.
Google/network identity responses remain explicit test mocks/local signed fixtures.
The temporary native API process, Redis server and PostgreSQL cluster were stopped
after verification; the ignored local test files remain available for future checks.

Initial Redis startup hit a sandbox MSYS signal-pipe denial, then an MSYS path error
with the absolute Windows config path. The interrupted run showed connection/setup
errors and was not counted as a pass. Correct relative configuration paths fixed
the disposable setup. The first successful complete run passed 49 tests with three
warnings. The strengthened separate-process worker test removed deprecated
`job.result` access in favor of `return_value`; final run passed 49 with only the two
existing Starlette/Authlib HTTPX deprecation warnings. Those warnings are not hidden.

### Phase 1 changes and pending execution

- `tests/test_infrastructure.py`: RQ smoke now proves distinct worker-process
  execution instead of running a SimpleWorker within the pytest process, uses
  current result access and cleans its queue/job in finally.
- `scripts/container_smoke.py`: prepared bounded real API/PostgreSQL/Redis and
  actual `ai`/`render` worker smoke for an isolated development Compose project.
  Dockerfile copies this script; it has NOT been run in a container.
- `.github/workflows/backend.yml`: added isolated Compose startup, container smoke
  and cleanup after build. CI has NOT run in this session.
- `docs/WINDOWS_DOCKER_SETUP.md`: exact user-run installation/configuration and
  later local container verification commands, with official references and current
  Windows support-policy caveat. README links the guide.

Docker build, Compose startup/health, official Linux Redis and regular Linux RQ
worker entrypoints remain **PENDING**. The Windows smoke is not evidence those
checks pass. Real Google credentials, live email, production deployment, Contabo
capacity/load, TLS and backup/restore also remain untested.

Local read-only setup checks found Windows 10 Pro 22H2 build 19045.6466,
8,547,581,952 bytes physical memory, enabled CPU virtualization/SLAT, no hypervisor,
and LanmanServer running/Automatic. Windows 10's normal support ended in 2025;
current OS servicing/Docker support eligibility needs resolution, not an assumed
compatibility promise. No upgrade or feature enablement was attempted.

**Readiness:** non-Docker Phase 1 checks pass. Phase 1 infrastructure gate remains
partial; Phase 2 remains pending and unstarted until local Docker installation and
the documented container checks actually succeed and the user authorizes Phase 2.

## Phase 1 Docker infrastructure verification — 2026-10-10

This verification supersedes the earlier Docker-pending follow-up. Phase 1 only;
Phase 2 remains unimplemented. Docker Desktop was already installed by the user.
No Contabo access, deployment, paid API call, live Google login or email delivery
was performed. No confirmed Phase 1 application defect surfaced, so no application,
dependency, migration, base Compose or environment-template changes were necessary.

### Isolation and resource precautions

Initial Docker inventory contained no containers or volumes and only hello-world.
Docker Desktop 4.94.0 / Engine 29.8.2 / Compose v5.5.1 reported 4,085,637,120 bytes
RAM (3.80 GiB). Initial free disk: C: 1,942,106,112 bytes (1.81 GiB),
D: 37,409,013,760 bytes (34.84 GiB). No data was overwritten or volumes pruned/deleted.

Used a new project `zoclip-phase1-verify`, `.env.example` development placeholders,
and an ignored local override `var/phase1-verification/compose.verify.yaml`.
The override gives migrate/api/both workers the same `zoclip-phase1:verify` image,
so only one application build was needed. Memory caps: DB 512m, migrate 256m,
API 512m, each worker 384m; Redis retains 256m. These caps apply only to this
foundation smoke, not media processing or production capacity. The base Compose
file remains unchanged. PostgreSQL and Redis receive temporary random loopback
ports only in this override (observed 55111 and 55110); base Compose publishes
neither. API remains on 127.0.0.1:8000. No private .env was read or replaced.

Tests used a newly created `zoclip_phase1_docker_test` database and Redis DB 15;
only this test DB underwent downgrade, and only Redis DB 15 was flushed by fixtures.
The application database `zoclip` and worker Redis DB 0 were separate.

### Exact commands and observed results

For the commands below, PowerShell argument array `$composeArgs` is shorthand for:

```powershell
$composeArgs = @('--project-name', 'zoclip-phase1-verify', '--env-file', '.env.example',
  '-f', 'compose.yaml', '-f', 'var/phase1-verification/compose.verify.yaml')
```

| Command / check | Actual result |
|---|---|
| `docker compose --project-name zoclip-phase1-verify --env-file .env.example config --quiet` | PASS, exit 0; existing Compose configuration valid |
| `docker compose @composeArgs config --quiet` | PASS, exit 0; verification override valid |
| `docker build --tag zoclip-phase1:verify --progress plain .` | PASS, exit 0; frozen production dependencies, Python 3.12.15, application installed as non-root image |
| `docker compose @composeArgs up --no-build --detach --wait --wait-timeout 180` | PASS, exit 0; API/DB/Redis healthy; both workers running; migrate exited 0 |
| Windows HTTP GET `/health/live`, `/health/ready` | 200 `{"status":"alive"}`; 200 `{"status":"ready"}` |
| Windows HTTP GET `/api/v1/auth/google/start` | 503 `google_unconfigured`, as expected with no credentials |
| `docker compose @composeArgs exec -T api python scripts/container_smoke.py` | PASS, exit 0; API readiness, PostgreSQL SELECT 1/migration head, Redis PING, ai result 42, render result 42 |
| `docker compose @composeArgs exec -T api alembic current` | PASS, exit 0; `39bc6d102a49 (head)` |
| `docker compose @composeArgs exec -T api alembic check` | PASS, exit 0; `No new upgrade operations detected.` |
| `docker compose @composeArgs exec -T db createdb -U zoclip zoclip_phase1_docker_test` | PASS, exit 0; new separate test database |
| `.venv/Scripts/python.exe -m pytest -q --tb=short --basetemp=var/phase1-verification/pytest-tmp` | **49 passed, 0 failed, 0 skipped, 2 warnings in 22.68s**, exit 0 |
| Pytest session migration fixture | Real Docker PostgreSQL upgrade head -> downgrade base -> upgrade head -> Alembic schema check passed on test database only |
| `test_real_redis_rq_roundtrip` | PASS; real Linux Redis TCP connection; separate host SimpleWorker process completes queued getpid and returns a different PID |
| Actual Compose `worker-ai` / `worker-render` logs | Both Linux RQ 2.12.0 Worker entrypoints consumed `_operator.add(20, 22)` and logged successful completion / Job OK; smoke fetched result 42 from each |
| `.venv/Scripts/ruff.exe check src tests scripts alembic` | PASS, exit 0; all checks passed |
| `.venv/Scripts/ruff.exe format --check src tests scripts alembic` | PASS, exit 0; 27 files already formatted |
| `.venv/Scripts/mypy.exe src` | PASS, exit 0; no issues in 18 source files |
| `.tools/uv/uv.exe lock --check --offline` | PASS, exit 0; resolved 71 packages; workspace-local UV cache/Python directories |
| `.venv/Scripts/python.exe scripts/export_openapi.py` | PASS, exit 0; SHA256 before/after equal; schema unchanged; contract tests passed in complete suite |
| `git diff --check` | PASS, exit 0; LF/CRLF notices only |
| PostgreSQL SQL `SELECT 1; SHOW timezone; SELECT version();` | 1; Etc/UTC; PostgreSQL 17.11 Debian/Linux |
| Redis `INFO server` | Redis 7.4.11; Linux 6.18.40.1-microsoft-standard-WSL2 x86_64 |
| Running-container inspection | All five services `OOMKilled=false`, `RestartCount=0` before intentional shutdown |
| `docker compose @composeArgs stop` | PASS, exit 0; verification containers stopped to release RAM; all three volumes retained |

Test environment (development placeholders only):

```text
TEST_DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@127.0.0.1:55111/zoclip_phase1_docker_test
TEST_REDIS_URL=redis://127.0.0.1:55110/15
```

The suite ran in the existing Windows Python environment against the Docker Linux
services; the application and both regular RQ workers ran inside Linux containers.
No extra development/test image or dependency download was required. The two
pytest warnings are the existing Starlette/Authlib HTTPX deprecations, not failures.
Initial sandbox Docker pipe access was denied; authorized elevated local execution
resolved this. No test failure or application startup failure occurred in this run.

Observed image digests:

- Application: `sha256:fbab0c7f821e1c9abb617d96d7cf7450b274c6d877f53aaab23499bb8a0b21d2`
- PostgreSQL: `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`
- Redis: `sha256:4fa24486b8bcca8eec45ee0eb166edc674795e53a2b53d1a9ef263eecebaac85`

A single idle memory sample was about 73 MiB API, 47 MiB per worker, 33 MiB DB and
5 MiB Redis; this is not a peak-memory measurement or load benchmark. Final free
space: C: 1,789,198,336 bytes (1.67 GiB), D: 35,999,719,424 bytes (33.53 GiB).
C: remains critically low. No image/cache/container/volume cleanup was performed.
Retained volumes: `zoclip-phase1-verify_postgres_data`,
`zoclip-phase1-verify_redis_data`, `zoclip-phase1-verify_mailbox`.
To resume these services without rebuilding, use the argument array above and
`docker compose @composeArgs up --no-build --detach --wait --wait-timeout 180`.
The local override is intentionally ignored under var; its memory/port/image
settings are documented above for reproduction. Base development data was untouched.

### Gate and remaining limitations

**Phase 1 local development gate: PASS. Ready for Phase 2 after explicit user
instruction; no Phase 2 code was implemented.** Only this status document and the
ignored verification override/test artifacts changed during this verification.
No new migrations or environment settings; revision remains 39bc6d102a49.

Not run: GitHub Actions itself, a full Linux pytest run, live Google identity flow,
production email, Contabo deployment/load, production TLS/proxy, least-privilege DB
role rollout, backup/restore, or later-phase media/provider/payment tests. Existing
OIDC tests use mocked HTTP/local signed tokens; email uses the development mailbox.
These are separate deployment/integration limitations, not claims of live services.
The 3.80 GiB Docker allocation and low C: space are unsuitable evidence for the
8-GB target's capacity or the future 20-GB media-headroom gate. Production readiness
remains unclaimed. No git commit was created.
