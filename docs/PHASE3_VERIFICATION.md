# Phase 3 isolated verification

These commands create local disposable data. Never substitute a customer DB,
deployment project, real account or paid provider. The test suite upgrades and
downgrades its `_test` database and drops generated test schemas. Redis DB 15 is
flushed. Existing Phase 1/2 databases and Contabo are outside this procedure.

## Controlled HTTPS environment

`compose.phase3-test.yaml` is an explicit test override, never a production file.
It publishes DB/Redis/API on random loopback ports, uses smaller verification
memory caps and a workspace media bind mount. The unchanged 20 GiB disk floor
still applies. It adds an **internal** Docker network with synthetic subnet
93.184.216.0/24 and assigns 93.184.216.10 to the fixture. This address is globally
classified by the unchanged importer but routed only inside this isolated test
network; no public address is contacted or claimed to belong to ZoClip. The fixture
has no published port and no external network. Do not reuse that subnet for a real
deployment. Resolve any local Docker subnet collision before running.

`scripts/https_fixture.py` generates a disposable two-day CA and a hostname-valid
certificate for `media.phase3.test`. Private test keys stay under ignored `var/`.
Only the fixture gets its server key; test API/AI containers receive the public CA
through SSL_CERT_FILE and exact hostname mappings/allowlist. Normal certificate
chain/hostname verification, DNS validation, numeric socket pinning, actual peer
checks and all redirect/IP restrictions remain enabled. There is no production
private-IP exemption or TLS-disable flag.

From the repository root (PowerShell or a shell accepting these Docker arguments):

```sh
docker build --tag zoclip-phase3:completion .
docker run --rm --network none --mount type=bind,source=D:/zoclip,target=/workspace --workdir /workspace zoclip-phase3:completion python scripts/https_fixture.py prepare var/phase3-completion/tls
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml config --quiet
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml up --no-build --detach --wait --wait-timeout 180
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml exec -T api python scripts/container_smoke.py
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml exec -T -e ZOCLIP_ISOLATED_SMOKE=1 -e ZOCLIP_HTTPS_SMOKE=1 -e HTTPS_FIXTURE_URL=https://media.phase3.test -e HTTPS_FIXTURE_PATH=/verify/source.mp4 api python scripts/ingestion_smoke.py
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml run --rm --no-deps -v ./scripts/https_fixture.py:/verify/https_fixture.py:ro api python /verify/https_fixture.py check /verify --fixture /verify/source.mp4
```

The `--mount` example uses this workspace's absolute Windows path; on another
machine substitute its absolute repository path. The checked-in override uses relative
bind paths, resolved against root compose.yaml. Leave the fixture off the default
network. Successful import tests verify exact bytes through API/outbox/real RQ/
ffprobe/private download; negative tests reject wrong MIME, oversize and private
redirects. The transport check rejects wrong TLS hostname, untrusted CA, missing
allowlist and a private destination. This is real socket/TLS traffic, not a mocked
HTTP connection. Public Internet origin availability is a separate unrun check.

## Complete Linux suite

Create the database **once** in this disposable project. The placeholder password
below belongs only to `.env.example` development verification.

```sh
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml exec -T db psql -U zoclip -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE zoclip_phase3_linux_test"
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml run --rm --no-deps --user 0 -v D:/zoclip:/workspace -w /workspace -e TEST_DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@db:5432/zoclip_phase3_linux_test -e TEST_REDIS_URL=redis://redis:6379/15 api python scripts/verify_phase3.py
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml exec -T api alembic check
docker compose --project-name zoclip-phase3-completion --env-file .env.example -f compose.yaml -f compose.phase3-test.yaml stop
```

The disposable runner uses root for bind-mounted dependency cache access and
installs exact uv.lock dependencies. API, fixture, maintenance and real RQ worker
services continue running as UID 10001 with dropped capabilities. PYTHONPATH
explicitly selects mounted current `src`, preventing an old cached project wheel
from masquerading as the code under test. Results go to ignored
`var/phase3-completion/linux-final.log`. Do not run Windows and Linux tests against
the same test DB/Redis DB concurrently. No production secrets or paid calls are used.

Tests cover an empty PostgreSQL upgrade/base/upgrade cycle, schema drift and
refusal to downgrade populated Phase 3 job history, plus the unchanged Phase 2
financial-history safety tests. Crash-boundary tests inject process loss before
promotion, before commit and after commit/lost acknowledgment. They do not claim
physical power-loss, disk-controller durability or backup restoration testing.

Windows uses the same pytest suite with TEST_DATABASE_URL targeting a disposable
local `_test` DB, TEST_REDIS_URL ending `/15` and FFPROBE_BINARY configured locally.
Windows may skip real symlink creation without its required privilege; Linux must
run that test. See IMPLEMENTATION_STATUS.md for actual counts and timings.
