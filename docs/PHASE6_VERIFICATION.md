# Phase 6 local verification — 2026-10-10

Scope: Phase 6 only, based on Phase 5 checkpoint 35032a0. Existing documentation
reconciliation changes are preserved. No real gateway, paid API, push, deployment,
frontend or Phase 7 implementation. Merchant sandbox/live acceptance is NOT LIVE;
Phase 4 real Deepgram/Gemini gate remains PENDING; production NOT APPROVED.

## Observed checks

| Check | Result |
|---|---|
| Focused native billing/config suite | 59 passed, zero failures/errors/skips, 39.71s; real Docker PostgreSQL/Redis |
| Full Linux Phase 1–6 gate | PASS 324 tests, zero failures/errors/skips, 418.93s; all 275 prior cases plus 49 billing cases |
| Final schema/configuration check | PASS 10 tests, 9.07s; OpenAPI validates and matches the updated raw-webhook body declaration |
| Ruff lint/format and mypy | PASS 97 Python files formatted, 62 application files typed; Linux gate and final native check |
| Migration drift and actual RQ | PASS running alembic check and both actual Linux worker arithmetic/financial smoke |
| Prior render/editor regression | PASS real upload/audio/HTTPS simulators/RQ/FFmpeg/private download/prepaid revision and one SETTLE |
| Docker build/config/startup | PASS zoclip-phase6:verify; isolated DB/cache/API/workers healthy, migration exit 0 |
| Running source/contract match | PASS all 62 application source SHA-256 values; running OpenAPI equals snapshot, 55 paths |
| Actual sandbox HTTP smoke | PASS authenticated order; forged signature/browser return grant zero; ten concurrent deliveries grant once; Alice/Bob isolation; manual helper sends verified refund; ledger reconciles |
| Lock resolution | PASS uv lock --check --offline; 73 packages; no dependency change |

Focused evidence: var/phase6-verification/native-focused.xml. HTTP/runtime evidence:
payment-smoke.log and runtime-match.log. Full Linux runner writes linux-final.log,
pytest.xml and gate-status.json; final-contract.xml records the final OpenAPI checks.
container-smoke.log, schema-drift.log and render-regression-smoke.log preserve the
runtime regressions. These files are ignored and never staged.

The full Linux suite includes upgrade -> base -> upgrade, schema drift and populated
financial/media/provider/render/payment downgrade guards. Gate marker is passed;
JUnit contains all 324 individual cases. After that suite, a passive OpenAPI
requestBody declaration was added for the exact SandboxNotification model already
used by the verifier. Its schema/configuration tests, lint/type and cached image
rebuild pass. Financial/handler behavior is unchanged; the expensive full suite was
not repeated for this declaration. Final source/schema equality is checked again.

New billing tests exercise actual independent PostgreSQL connections for ten-way
duplicate checkout and event delivery, success/reversal races, and provider event-ID
collision across owners. They cover grant rollback/redelivery, late payment and
delayed delivery, immutable terms/evidence, price-version pinning/sequential renewal,
full reversal before/after success, spent/held credit exposure and account hold,
unknown outbound refund with no retry, reasoned query reconciliation and RBAC/IDOR.
Production mock/live switches, malformed/stale signatures, wrong amounts/currency/
reference, body limits and private configuration leakage are checked.

Initial restricted native attempts could not use pytest temporary directories;
they are not acceptance evidence. Running with normal local permissions resolved
that setup boundary. One test called a nonexistent credit-release helper; corrected
to the existing trusted finish contract. Final focused result above passes.
The first Compose startup used a newer .NET random-byte API unavailable in Windows
PowerShell; secret configuration remained empty and validation safely stopped
migration/startup. Retrying with RandomNumberGenerator.Create/GetBytes succeeded.
The generated key was never printed or committed. Two existing HTTPX deprecation
warnings remain. No live credential, provider account or paid network call was used.

## Reproduce in an isolated local project

Use disposable PostgreSQL, Redis DB 15, .env.example placeholders and the existing
isolated CA fixtures from PHASE4_VERIFICATION.md. The override is not deployment
configuration. Keep prior verification volumes and unrelated Docker projects intact.
The existing zoclip-phase4-verify project was reused; only its test services changed.

```powershell
docker build --tag zoclip-phase6:verify .
$sandboxKeyBytes = New-Object byte[] 32
$sandboxRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$sandboxRandom.GetBytes($sandboxKeyBytes)
$sandboxRandom.Dispose()
$env:PAYMENT_PROVIDER = 'mock'
$env:PAYMENT_MOCK_WEBHOOK_SECRET = [Convert]::ToBase64String($sandboxKeyBytes)
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase6-test.yaml config --quiet
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase6-test.yaml up --no-build --detach --wait --wait-timeout 180
```

Create zoclip_phase6_linux_test only if absent in that disposable PostgreSQL.
Never run the up/down/up suite on a populated or customer database.

```powershell
docker exec zoclip-phase4-verify-db-1 psql -U zoclip -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE zoclip_phase6_linux_test'
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase6-test.yaml run --rm --no-deps --user 0 -v D:/zoclip:/workspace -w /workspace -e TEST_DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@db:5432/zoclip_phase6_linux_test -e TEST_REDIS_URL=redis://redis:6379/15 api python scripts/verify_phase6.py
docker cp scripts/payment_smoke.py zoclip-phase4-verify-api-1:/tmp/payment_smoke.py
docker cp scripts/payment_sandbox.py zoclip-phase4-verify-api-1:/tmp/payment_sandbox.py
docker exec -e ZOCLIP_PAYMENT_SANDBOX_SMOKE=1 zoclip-phase4-verify-api-1 python /tmp/payment_smoke.py
docker exec zoclip-phase4-verify-api-1 alembic check
docker exec zoclip-phase4-verify-api-1 python scripts/container_smoke.py
docker exec -e ZOCLIP_AI_SIMULATOR_SMOKE=1 -e ZOCLIP_RENDER_SIMULATOR_SMOKE=1 zoclip-phase4-verify-api-1 python /verify/render_smoke.py
docker run --rm --network zoclip-phase4-verify_default -v D:/zoclip:/workspace:ro -e DATABASE_URL=postgresql+psycopg://schema@db/schema zoclip-phase6:verify python /workspace/scripts/verify_runtime.py
```

Full runner clears AI/provider/payment environment overrides before lint/type/pytest;
mock billing is installed explicitly by the tests. Simulator HTTP smoke uses only
the private local mock secret. The source check reads the installed image and real
running API, not just a separately generated schema. The smoke adds immutable
fictional financial history only in this disposable database; it must not run on
customer data. Missing ZOCLIP_PAYMENT_SANDBOX_SMOKE rejects before DB/network.

## Migration/configuration and unrun boundaries

### Resumption review — 2026-10-10

Fresh native checks on the resumed working tree:

- `.venv/Scripts/python.exe -m pytest tests/test_config.py -q --tb=short -p no:cacheprovider`
  — 10 passed, two existing HTTPX deprecation warnings, 7.53s.
- `.venv/Scripts/ruff.exe check src tests scripts alembic` — all checks passed.
- `.venv/Scripts/ruff.exe format --check src tests scripts alembic` — 97 files formatted.
- `.venv/Scripts/mypy.exe src` — no issues in 62 source files.
- `git diff --check` — passed.

A read-only SHA-256 comparison confirms all 62 current application sources match
the saved `runtime-match.log` manifest. Saved JUnit reports independently contain
324 Linux cases, 59 focused native cases and 10 final contract cases, each with
zero failures/errors/skips; `gate-status.json` records `passed`. These are saved
execution results, not newly rerun integration tests. The first manifest read
used the wrong log encoding; decoding the PowerShell UTF-16 log corrected the
reader and the comparison passed. No application change was required.

This follow-up updates verification documentation only. The full Linux suite,
Docker runtime/migrations and merchant/provider gates were not rerun; no new
migration, configuration, commit, deployment or Phase 7 implementation was made.

Forward revision 651ba28dacf9 follows a580f314c921 and adds orders, immutable
checkout references/events, full refunds/chargebacks, append-only entitlement
revocations, durable refund intents and reasoned staff reconciliation records.
Database guards prevent changing order terms, erasing payment history or mutating
gateway evidence. Downgrade refuses any populated billing history. Prior revisions
and immutable ledger/entitlement records are preserved; no destructive backfill.

New PAYMENT_MOCK_WEBHOOK_SECRET is blank by default, SecretStr/redacted and required
only for explicit non-production mock mode. PAYMENT_PROVIDER adds a clearly disabled
jazzcash choice. Production payments and automatic trials remain rejected. No real
merchant endpoint, price, fee or secret is added; dependencies/lock are unchanged.

Unrun: merchant sandbox/live onboarding and verified callback/query/refund contracts,
real Deepgram/Gemini gate, representative quality/capacity/economic benchmarks, full
Windows regression, Ubuntu/VPS deployment, backups/restores and remote CI. These
remain acceptance boundaries; the local sandbox cannot substitute for merchant proof.
Risk debt is retained and access held; debt resolution/re-enablement needs a separate
approved audited operational policy. Partial refunds and recurring billing are absent.
Next requested implementation would be Phase 7 only after explicit authorization.

## Completion checkpoint

The user selected reviewing and finishing the current Phase 6 work. Final review
found no additional application defect requiring changes. The local checkpoint
saves the reviewed implementation, migration, tests, example configuration,
generated contract and handoff. Saved and fresh checks are distinguished above;
the earlier statements that no commit existed describe the pre-checkpoint state.
No verification artifacts, private configuration or secrets enter the checkpoint.
No push, deployment, live provider calls or Phase 7 work are included.
