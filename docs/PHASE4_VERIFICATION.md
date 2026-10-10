# Phase 4 local verification and audit

Date: 2026-10-10. Baseline: Phase 3 commit `e67832a`.
The user subsequently authorized a local Phase 4 checkpoint based on this evidence.

- **Phase 4 local mock/fixture gate: PASS.**
- **Phase 4 real Deepgram/Gemini provider gate: PENDING.**
- **Production readiness: NOT APPROVED.**
No live paid API request, deployment, push or Phase 5 work was performed.

## Resumption audit

The implementation was approximately 85–90% complete at inspection: the AI
package, migration, API schema, 50 AI tests and simulator scripts already existed.
The status and handoff documents had not been updated. The saved
`var/phase4-verification/linux-final.log` contained a completed 233-test pass,
lint/format/type passes; it did not end mid-suite. The Phase 4 Compose services
were still running, migration had exited 0, and worker logs showed simulator
transcription/analysis tasks completing. There was no final acceptance report or
commit. This supports an unfinished handoff, not a proven interrupted pytest run;
the exact prior session termination reason cannot be reconstructed from these
artifacts. Prior Windows temporary directories are not evidence of successful tests.
The prior Linux log was preserved as `prior-linux-final.log` before rerunning.

Existing work was retained. Corrections on resumption:

- Reconcile cancellation/crash receipts before cleanup; mark missing evidence
  UNKNOWN while retaining exposure. Void freshly admitted calls proven unsent.
- Remove system_limits-before-storage lock acquisition from error/recovery paths;
  retain consistent owner/wallet -> storage/job -> expense-system ordering.
- Add bounded backoff for local AI recovery retries.
- Reject known synthetic/fictional provider key placeholders in production.
- Add four AI regression cases, opt-in live-smoke tooling (not run), runtime source
  comparison, command/status/JUnit evidence, configuration/privacy/API handoffs.

No prior Phase 1–3 migration was rewritten. The existing Phase 4 migration
`91731e381b3a` follows `7e3fcb0834e3`, adds ai_requests/transcripts/clip_suggestions
and SUGGESTIONS_READY. Downgrade refuses populated provider history. All prior
wallet constraints and history remain intact. No dependency or lock update needed.

## Actual results

| Check | Result |
|---|---|
| Linux full pytest, actual PostgreSQL/Redis, mocked providers and real FFmpeg | **237 passed, 0 failed, 0 errors, 0 skipped**, 202.49s |
| Windows full pytest, same actual container PostgreSQL/Redis, native FFmpeg | **236 passed, 0 failed, 0 errors, 1 skipped**, 226.93s |
| Ruff lint and format | PASS; final check covers 69 Python files |
| mypy src | PASS, 45 source files |
| uv lock --check --offline | PASS, 71 resolved packages, unchanged lock |
| Empty PostgreSQL migration upgrade -> base -> upgrade and drift check | PASS in full suite |
| Populated Phase 2/3/4 downgrade guards | PASS in full suite |
| Running API container alembic check | PASS, no new upgrade operations |
| Docker build zoclip-phase4:verify | PASS |
| Base + Phase 4 Compose config --quiet | PASS |
| Isolated Compose startup with rebuilt image | PASS; API/DB/Redis healthy, migration exit 0, workers/maintenance/fixture running |
| container_smoke.py | PASS API/readiness/migration, PostgreSQL grant/reconcile/rollback, Redis, both actual Linux RQ workers (42) |
| ai_smoke.py with simulator opt-in | PASS actual API/upload/outbox/RQ/FFmpeg/HTTPS REST adapters; validated timings/suggestions; two jobs reuse one Deepgram/one Gemini call; three usage records; no SETTLE; cancellation once; privacy cleanup |
| ingestion_smoke.py with controlled HTTPS opt-in | PASS upload/exact private download/lease cleanup/capacity; HTTPS redirects/MIME/oversize/private redirects |
| https_fixture.py check | PASS trusted CA, wrong hostname/untrusted CA/absent allowlist/private IP rejection |
| Running image vs working source | PASS all 45 Python files, saved SHA-256 manifest |
| OpenAPI | PASS validator and generated-route snapshot test; running API equals snapshot, 42 paths |
| Optional live smoke safety guard | PASS invocation without paid opt-ins rejected before Settings/DB/network |

Linux exact per-module results from JUnit:

| Module | Passed | Failed | Skipped |
|---|---:|---:|---:|
| test_ai.py | 54 | 0 | 0 |
| test_auth.py | 19 | 0 | 0 |
| test_config.py | 10 | 0 | 0 |
| test_credits.py | 66 | 0 | 0 |
| test_google.py | 19 | 0 | 0 |
| test_infrastructure.py | 1 | 0 | 0 |
| test_media.py | 68 | 0 | 0 |

Every parameterized test name and duration is in local
`var/phase4-verification/pytest.xml`; complete suite output is `linux-final.log`.
`gate-status.json` reports passed for the Linux lint/type/pytest runner, not live
Gate 4. Other evidence files: container-smoke.log, ai-smoke-final.log,
ingestion-smoke.log, https-transport.log and runtime-match.log. Logs are ignored
local artifacts and are not fabricated CI results.
After verification, only the Phase 4 test Compose project was stopped; volumes,
databases, media test artifacts and logs were preserved. Other Docker projects
were left unchanged. At the initial audit handoff no new commit was created; HEAD was
`e67832a0d2f356a222011daa87d237cbe58a4b76`.

Windows has the same per-module counts except test_media.py: 67 passed, 1 skipped.
The exact skip is `test_storage_rejects_path_traversal_and_symlinks` at test_media.py:878,
because Windows symlink privilege is unavailable; the Linux suite exercises that
test successfully. Full Windows results are windows-final.log and
windows-pytest.xml. Its separate disposable DB is
zoclip_phase4_resume_windows_test; Docker loopback PostgreSQL/Redis ports on this
run were 61383/61380. FFmpeg/ffprobe used ignored native 9.0.2 tools. No prior
Phase 1–3 database or repository auth implementation was altered.

One AI smoke invocation used the ingestion opt-in instead of
ZOCLIP_AI_SIMULATOR_SMOKE; its safety guard rejected execution before any request.
The corrected command passed. The failed invocation remains in ai-smoke.log;
it is not counted as a passing run. Intermediate lint/type errors while editing
were corrected before the final checks. Two existing Starlette/Authlib HTTPX
deprecation warnings remain; they are not suppressed.

## Reproduce safely

Use only disposable local data, synthetic credentials and the test override.
The internal provider fixture maps official provider hostnames inside these
containers to synthetic address 93.184.217.10. It has no external network or
published port. Only a disposable fixture CA is trusted; TLS verification stays
enabled. No system trust store or production provider destination is changed.
Do not use this override with live credentials or a deployment project.

```sh
docker build --tag zoclip-phase4:verify .
docker run --rm --network none --user 0 --mount type=bind,source=D:/zoclip,target=/workspace --workdir /workspace zoclip-phase4:verify python scripts/ai_https_fixture.py prepare var/phase4-verification/tls
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml config --quiet
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml up --no-build --detach --wait --wait-timeout 180
```

The prepare command is for a fresh fixture directory; do not rotate certificates
under running services. This resumption reused the existing disposable test CA.
Create the disposable suite database once, only if absent:

```sh
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T db psql -U zoclip -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE zoclip_phase4_linux_test"
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml run --rm --no-deps --user 0 -v D:/zoclip:/workspace -w /workspace -e TEST_DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@db:5432/zoclip_phase4_linux_test -e TEST_REDIS_URL=redis://redis:6379/15 api python scripts/verify_phase4.py
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T api python scripts/container_smoke.py
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T -e ZOCLIP_AI_SIMULATOR_SMOKE=1 api python /verify/ai_smoke.py
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T -e ZOCLIP_ISOLATED_SMOKE=1 -e ZOCLIP_HTTPS_SMOKE=1 -e HTTPS_FIXTURE_URL=https://media.phase3.test -e HTTPS_FIXTURE_PATH=/verify/source.mp4 api python scripts/ingestion_smoke.py
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T api python /verify/https_fixture.py check /verify --fixture /verify/source.mp4
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml run --rm --no-deps -v D:/zoclip:/workspace:ro api python /workspace/scripts/verify_runtime.py
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase4-test.yaml exec -T api alembic check
```

The root runner installs uv.lock dependencies and uses mounted /workspace/src,
not a stale installed wheel. Runtime API/workers stay UID 10001 with capabilities
dropped. Suite DB names must end `_test`; Redis DB 15 is flushed. Never run
Windows/Linux suites against that Redis DB concurrently. Windows paths above
are this workspace's paths; substitute the actual workspace elsewhere.

## Acceptance boundaries

Local mock/fixture acceptance passes. The specification's Gate 4 requires a real
configured transcription and useful validated suggestions. That check is **NOT
RUN**, as the user explicitly prohibits real paid calls. The subsequent user
authorization permits a local checkpoint commit based on the passing mock/fixture
gate; it does not waive or satisfy the real-provider gate. Production readiness
is **NOT APPROVED**.
Do not supply keys in chat or treat simulator output as real provider evidence.

Not run: actual vendor account/model/pricing/429 billing semantics acceptance,
subjective highlight-quality review, representative 10/30/60/120-minute throughput,
physical power-loss, backups/restores, Ubuntu 24.04/VPS rollout or GitHub Actions.
Docker verification uses the repository's Python 3.12 Bookworm Linux image, not
an Ubuntu host acceptance claim. Unknown provider expenses require manual trusted
evidence; automatic invoice reconciliation is absent. A generic configured Gemini
model must support the adapter's reviewed schema/thinking options. Long transcripts
may fail configured chunk/expense caps safely. Retention/commercial terms and
runtime DB privilege separation still need approval/operational verification.
See AI_HANDOFF.md for limits and data-processing disclosure.

Before the checkpoint, current application bytes are compared with the recorded
45-file SHA-256 manifest; reviewed staging excludes private keys, real credentials,
logs, JUnit/test outputs, databases and ignored tooling. Synthetic fixture markers
and CHANGE_ME configuration placeholders are not functional provider credentials.
Existing verification evidence is preserved locally under ignored var/.

Real-provider verification requires a new explicit decision permitting paid calls.
Phase 5 has not begun; no render/editor/export or completed deliverable is claimed.
