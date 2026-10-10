# Phase 7 verification evidence — 2026-10-11

**Local infrastructure gate: PASS. VPS deployment: UNVERIFIED / NOT APPROVED.**

Scope: private local preparation from Phase 6 commit `6e82cce`. No Contabo SSH,
VPS changes, DNS/public ports, live credentials, paid API calls, live payments,
push or Phase 8. Production launch is NOT APPROVED. Phase 4 live-provider and
Phase 6 merchant verification remain pending.

The isolated project `zoclip-phase7-verify` uses its own PostgreSQL 17 / Redis 7.4,
private networks/volumes, loopback HTTPS 18443/admin 18444 and synthetic credentials,
certificate and age identity under ignored `var/phase7-verification/`. Existing
phase projects' data/volumes were preserved. Only this test project's services
are stopped after verification; its recovery evidence/volumes are retained.

## Final observed checks

| Check | Actual result |
|---|---|
| Full Linux regression gate | **334 passed, 0 failed, 0 errors, 0 skipped**, 451.63s; 324 Phase 1–6 cases + 10 operations cases; matching JUnit and passed gate marker |
| Separate final backup security suite | **10 passed, 0 failed, 0 errors, 0 skipped** on Linux (0.29s) and Windows (0.21s); added after the full 334-case run, not a claimed single 344-case run |
| Native final static checks | Ruff lint/format **117 Python files**; mypy **70 source files**; validated OpenAPI; offline lock check resolves 73 packages |
| Installed production image contract | Exact hashes of **70 sources**, production-factory schema **56 paths**, match repository |
| Compose/build/startup | Final app/tools builds and configuration pass; all seven steady services healthy; migration at `7b37ea061d28`, drift check passes |
| Publication/secrets/container boundaries | Only proxy loopback ports; no DB/Redis/API/worker publication; secret files excluded from image/environment/history; non-root/read-only/capability/resource limits verified |
| HTTPS/proxy/auth/CORS | Fixture CA validated; host/origin/body limits, unauthenticated access, private admin, overwritten proxy headers, single security headers and no-store pass |
| Actual RQ / runtime PostgreSQL privileges | Both Linux queues execute fixture arithmetic 42; runtime DDL, version mutation, financial deletion and audit truncation refused; financial rollback/idempotency smoke passes |
| Bounded stress | 100 health requests, 8 client threads: **22 HTTP 200, 78 HTTP 429**; verifies rejection behavior, not video throughput |
| Dependency failures | Redis and DB stopped separately: readiness failure then healthy recovery; actual RQ and migration checks pass afterward |
| Process crashes | SIGKILL application children in API, AI worker, render worker and maintenance; restart counters increase and health recovers |
| Backup/restore | Encrypted DB and media backup, ciphertext hashes, separate-target restore, exact ledger delta comparison, all-wallet reconciliation, schema and media hash, overwrite refusal pass |
| Deployment controller | Explicit execution required; new-empty shortcut rejected on populated DB before migration; existing-container resume does not rerun migrator; incompatible image rollback rejected; unquiesced backup refused |
| Local alert behavior | Host checker exits 1 with expected `tls_renewal_due` for two-day fixture cert and `proxy_429_spike` (78 observed); no unexpected alerts |

The full Linux gate uses actual PostgreSQL concurrency/constraints, disposable
Redis, real FFmpeg fixtures and controlled HTTPS provider simulators. It includes
login/CSRF, SSRF redirect/connected-IP checks, traversal/IDOR, malicious media,
concurrent wallet spend, webhook replay, duplicate work and RBAC regressions.
Failure evidence includes `test_http_failures_no_implicit_paid_retries` (429),
`test_analysis_failure_preserves_transcript_and_sunk_cost` (timeout),
`test_full_disk_and_retained_limit_fail_closed`,
`test_failure_does_not_settle_or_destroy_source` (FFmpeg), and checkpoint/commit
failure recovery. No real provider receives traffic. New operations tests cover
audited reports, exact Decimal/PKR serialization, fee deduplication, privacy
idempotency/financial preservation, auth expiry, disk and provider-breaker alerts.
Backup tests cover safe extraction, traversal/links, duplicate overwrite and
headroom; Linux verifies mode0600 permissions (Windows mode bits are conditional).

## Encrypted recovery evidence

- Manifest: `20261010T193139-a5edfc48.json` (UTC filename).
- Separate restored database: `zoclip_phase7_833d7fc7_restore_test`.
- Separate restored volume: `zoclip-phase7-verify_restore_media_833d7fc7`.
- Private synthetic media SHA256:
  `94aacacba58344ed719006a1ec2d5e41b5c85a4d1ac005ec9aecd228513115bc`.
- Ledger fixture deltas compare exactly; every restored wallet reconciles;
  migration head matches; repeat restore refuses populated targets.
- Database/media bytes reach backup disk only as age ciphertext. The original
  fixture recovery identity stays mode0600 outside services; temporary restore
  single-file identity mounts are removed afterward. No live identities used.

This is a **local** restore. Off-server transfer/retrieval, independent recovery
host and measured recovery objectives remain unverified. Failed early separate
restore targets are retained for diagnosis, never promoted or overwritten.

Final local application image manifest digest:
`sha256:75c1f1ff371ce1ae835d93c40121cf2532d3ec2309f8ce25c85ccf1849fe3946`.
Final tools image manifest digest:
`sha256:51fa31a8866db6550e379c73c5a1efc5b03a88619e49bf8140475ac782e32405`.
App uses Python 3.12; Debian PostgreSQL tools image uses Python 3.11.2 and age
1.1.1. Base/uv/DB/Redis/Nginx references are pinned in source; OS security packages
resolve at build time, so these resulting digests identify the verified images.

## Earlier attempts and corrections

- Native fallback: **94 passed, 239 skipped**, zero failures/errors, 22.51s.
  PostgreSQL-dependent and one Windows-specific case skipped; this predates the
  final added usage/backup cases and is not the full acceptance gate.
- Initial sandbox native attempts: 78 passed, 238 skipped, 17 temporary-directory
  ACL setup errors. Dedicated workspace temp outside that sandbox resolved them.
- First complete Linux run: 332 passed, 1 failed, 388.34s. A new monitor fixture
  incorrectly expected a seeded enabled policy to be disabled. Corrected fixture
  and added exact recorded-usage JSON coverage; complete rerun passed 334 cases.
- Initial native backup suite: 9 passed, 1 failed because Windows does not enforce
  POSIX mode bits. Scoped that assertion to Linux; final suites pass on both.
- Initial startup issues fixed: quoted tmpfs commas/Nginx regex; all Nginx temporary
  paths under tmpfs; proxy-only ingress bridge for loopback forwarding; lightweight
  maintenance heartbeat probe under 0.25 CPU quota; per-boot RQ worker identity.
- Drill fixes: inject fixture code through stdin into read-only containers; kill
  application children instead of an explicit Docker operator kill (which suppresses
  restart); resume exact container IDs because Compose start follows migrator deps.
- Initial encrypted restore failed on private-key mount readability, then on Python
  3.11 tarfile filter API incompatibility. Fixed protected temporary single-file
  mount and explicit streaming safe extraction; rebuilt tools, passed ten focused
  security tests and reran the complete infrastructure/restore drill successfully.
- Two networked gate attempts were interrupted by unresponsive Docker Desktop;
  no pytest result claimed. Docker VM has about 3.8 GiB RAM, distinct from target
  8 GB; dependency DNS/download failure also occurred. Normal restart failed.
  Auto-review rejected forced recovery until the user explicitly approved local
  Docker/WSL recovery. Images/volumes preserved; unrelated restart-policy services
  returned. Host committed memory reached 96%; lightweight cmd shell/offline
  locked dependency cache completed verification. Retained runner OOMKilled=false;
  no unsupported claim that the application caused the engine failure.

## Reproduction

Build `docker build -t zoclip-phase7:verify .` and
`docker build -f deploy/Dockerfile.ops -t zoclip-ops:phase7 .`, then run
`scripts/prepare_phase7.py` with explicit
`ZOCLIP_PHASE7_LOCAL_FIXTURES=1` once in a fresh ignored fixture directory. It
refuses existing credentials; it is not a server provisioning tool. Start the
isolated Compose. Create only the disposable regression DB, not a live database:

```sh
docker compose -p zoclip-phase7-verify --env-file var/phase7-verification/staging.env -f deploy/compose.yaml exec -T db psql -U zoclip_bootstrap -d postgres -c "CREATE DATABASE zoclip_phase7_linux_test OWNER zoclip_bootstrap"
docker compose -p zoclip-phase7-verify --env-file var/phase7-verification/staging.env -f deploy/compose.yaml -f deploy/compose.test.yaml run --rm --no-deps test-runner
# If the complete locked cache already exists, add -e ZOCLIP_PHASE7_OFFLINE=1.
docker compose -p zoclip-phase7-verify --env-file var/phase7-verification/staging.env -f deploy/compose.yaml -f deploy/compose.test.yaml run --rm --no-deps --entrypoint uv test-runner run --frozen python -m pytest tests/test_backup_ops.py -q
python scripts/phase7_smoke.py --local-fixtures
python scripts/phase7_controller_smoke.py --local-fixtures
```

Do not run dependency failure drills while regressions use DB/Redis. The smoke
helper requires the exact isolated project/origin; it stops writers for backup
and creates unique empty restore targets. Fixtures under tests/fixtures required.
Static checks use Ruff, mypy src and `scripts/export_openapi.py` per pyproject.

Ignored evidence includes linux-final.log, pytest.xml, gate-status.json,
backup-tests-linux.xml, backup-tests-native-final.xml, native-elevated.log,
native-pytest-elevated.xml, infrastructure-results.json, controller-results.json
and ciphertext/manifest under var/phase7-verification. Never stage private
fixtures, image layers, runtime logs, DB/media volumes, package cache or identities.
The updated tracked OpenAPI is the required API contract, not runtime evidence.

## Unrun real-world gates

Actual Contabo Ubuntu startup/resource/host-reboot and systemd validation;
independent external IPv4/IPv6 scan/firewall/SSH validation; image vulnerability
scan/SBOM review; DNS-01 real TLS issuance/renewal; off-server backup retrieval and
restore; outbound alert delivery; approved RPO/RTO/retention/legal privacy/provider
deletion policy; invoice/FX/margin assumptions; representative video throughput,
quality/capacity; email/Google configuration; Phase 4 live-provider and Phase 6
approved merchant acceptance. Previous-image rollout was not attempted: no prior
verified Phase 7 release exists; compatibility rejection is verified. No local
result waives these gates. See DEPLOY_CONTABO.md for required server/domain/backup
inputs. No push or Phase 8 work is authorized/performed.
