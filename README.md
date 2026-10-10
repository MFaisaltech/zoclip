# ZoClip backend

Phases 1–2: FastAPI/PostgreSQL authentication, credits, plans and expense protection.
No payments, uploads, AI processing or clip rendering yet. See `docs/IMPLEMENTATION_STATUS.md`
for actual checks and remaining gates. No paid provider calls are made.

## Local Docker setup

Requires Docker Engine with Compose v2. These commands are provided for a Docker
host. Local Docker build/start and the isolated infrastructure gate are recorded
in the implementation status; this is not a production deployment claim.

For local Windows installation and isolated container checks, follow
[WINDOWS_DOCKER_SETUP.md](docs/WINDOWS_DOCKER_SETUP.md). Contabo remains untouched.

```sh
cp .env.example .env
# Edit .env privately. Replace CHANGE_ME in BOTH POSTGRES_PASSWORD and DATABASE_URL
# with the same URL-safe random development password. Never commit .env.
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
```

The migration service runs once before API/workers. Database/Redis have no host
ports; API binds host loopback only. One worker listens on `ai`, one on `render`;
neither has media/product tasks yet. App containers run as UID 10001 with dropped
capabilities. Persistent volumes hold DB, Redis and development mailbox data.
Do not run `down --volumes` against data you need.

`.env.example` explicitly enables HTTP-compatible local cookies and development
mailbox. Production validation requires HTTPS, secure cookies, real allowed hosts
and no development mailbox/mock payment mode. Production email is disabled in this
phase; register/reset return `email_unconfigured`. Compose is a foundation, not a
finished Contabo production rollout: TLS/Nginx, least-privilege DB roles, backups,
restore, monitoring and deployment verification remain later gates.

For a local development flow, use `/docs` or the steps in `docs/AUTH_HANDOFF.md`.
Read verification/reset messages privately with:

```sh
docker compose exec api sh -c 'ls /app/var/mailbox'
docker compose exec api cat /app/var/mailbox/<message-id>.json
```

Those files contain development-only recipient addresses and bearer tokens.
Never publish them, mount them publicly, log them or copy them into issues.

## Python development and checks

Python 3.12 and uv 0.12.24 are used. `uv.lock` fixes resolved package versions and
hashes across supported platforms. Do not replace the PostgreSQL test DB with SQLite.

```sh
uv sync --frozen
export DATABASE_URL='postgresql+psycopg://<user>:<password>@localhost:5432/<database>'
export REDIS_URL='redis://localhost:6379/0'
export EMAIL_MODE=development
export COOKIE_SECURE=false
uv run alembic upgrade head
uv run uvicorn zoclip.main:create_app --factory --no-access-log --no-proxy-headers
uv run ruff check src tests scripts alembic
uv run ruff format --check src tests scripts alembic
uv run mypy src
uv run python scripts/export_openapi.py
```

Integration tests require an explicitly disposable PostgreSQL database whose name
ends in `_test`. The fixture upgrades, **downgrades to base**, upgrades again and
checks schema drift. Never point it at a database containing data you want to keep.
Optional `TEST_REDIS_URL` must target disposable DB 15; fixtures flush that DB.
Without it, auth rate tests use fakeredis with Lua and the real Redis/RQ smoke skips.
The RQ test starts a separate portable worker process and verifies its returned PID;
the container smoke separately checks the real Linux `ai` and `render` entrypoints.

```sh
export TEST_DATABASE_URL='postgresql+psycopg://<test-user>:<test-password>@localhost:5432/zoclip_ci_test'
export TEST_REDIS_URL='redis://localhost:6379/15'
uv run pytest -q
```

PowerShell uses `$env:TEST_DATABASE_URL='...'` instead of `export`. The GitHub Actions
workflow provisions disposable PostgreSQL/Redis and runs lint/type/schema/tests and
Docker validation/build. A workflow file is not evidence of a successful CI run.

Google is disabled unless all three GOOGLE variables are supplied privately and
the callback URI is registered. No SMTP adapter is claimed; the email interface
currently has disabled and development-only implementations. See the auth handoff
for configuration and security details.

## Credits and plans

Read [CREDITS_AND_MARGIN.md](docs/CREDITS_AND_MARGIN.md) and
[API_HANDOFF.md](docs/API_HANDOFF.md) for the actual Phase 2 routes, staff configuration
and caller-owned financial transaction contracts. The migration seeds catalog
names only; all prices, allowances, rules and cost budgets are unset. New accounts
have no automatic credits. Paid work is disabled until a complete audited policy
and rates exist. Prices remain unapproved until explicitly reviewed.

Expiry is disabled; unused credits carry over. Access is prepaid 30 days without
automatic renewal. No customer purchase or payment callback can grant credits in
this phase. Financial tests use fictional staff grants/rates and no paid APIs.
Concurrency tests migrate/drop generated schemas within the disposable _test DB;
the test DB role must be allowed to create schemas. Never grant that privilege to
the production runtime role just to run tests.
