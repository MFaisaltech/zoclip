# Phase 5 local acceptance — 2026-10-10

**Local mock/fixture gate: PASS. Real Deepgram/Gemini gate: PENDING.
Production readiness: NOT APPROVED.** Baseline is Phase 4 checkpoint 13a886e.
Scope is Phase 5 only, no paid calls/push/deployment/payments/frontend/Phase 6.

## Final checks and evidence

| Check | Actual result |
|---|---|
| Complete Linux pytest | 275 passed, 0 failed, 0 errors, 0 skipped; 376.30s |
| Modules | AI 54, auth 19, config/OpenAPI 10, credits 66, Google 19, infrastructure 1, media 68, rendering 38 |
| Ruff lint/format | PASS; full Linux runner plus final current-tree check, 86 Python files |
| mypy | PASS, 56 source files; Linux runner and final current-tree check |
| uv lock --check --offline | PASS, 73 resolved packages; existing versions preserved, adds locked OpenCV/NumPy |
| Migrations | PASS upgrade -> base -> upgrade, drift, populated financial/ingestion/provider/render downgrade guards in pytest |
| Running DB alembic check | PASS, no new upgrade operations |
| Docker build/config/startup | PASS, final zoclip-phase5:verify; DB/Redis/API healthy, migration exit 0, workers running |
| Actual RQ workers | PASS ai/render arithmetic smoke and actual fixture pipeline |
| Simulator render smoke | PASS authenticated upload -> actual FFmpeg audio -> HTTPS Deepgram/Gemini fixtures -> saved selection -> render RQ -> verified MP4/private download -> caption/trim revision -> prepaid single re-render -> one SETTLE -> deletion |
| Concurrent API smoke | PASS simultaneous duplicate selection and export requests, same job/output, one charge |
| Phase 4 API smoke | PASS cache reuse, durable cost receipts, held credits, cancel once, privacy cleanup |
| Phase 3 API/HTTPS smoke | PASS upload/private download/outbox/RQ/ffprobe, real controlled TLS redirects/MIME/oversize/SSRF blocks, lease cleanup/capacity |
| Parent-death protection | PASS actual SIGTERM of Linux render parent kills its running child |
| Runtime/source/OpenAPI | PASS all 56 installed source SHA-256 values match current source; live schema equals snapshot, 48 paths |
| Diff and staged-file review | PASS required before local commit; private credentials/tooling/evidence are ignored and excluded |

Two existing HTTPX-related deprecation warnings remain; no final test failure or
skip remains. Development failures in Windows read-only fsync and fixture expectations
(padding/feature quote, DELETE 204, decimal FFmpeg seek syntax) were corrected.
Two early native fixture preparations were stopped during a loopback connection
wait; they do not count as passed tests. The complete final Linux gate completed,
its JSON marker says passed and its JUnit contains all individual cases.
Full Windows Phase 5 regression was not rerun; Linux is the target worker boundary.

Rendering tests check non-keyframe red/blue frame boundaries and 440/880Hz audio
markers, audible audio, original 500ms audio offset, actual burned-caption pixels,
clip-relative word intervals, malformed/overlapping/injection/Unicode text, presets,
vertical dimensions for landscape/portrait/square/low-resolution fixtures, real
bounded OpenCV subprocess and crop smoothing/fallback. They exercise cancellation
before and during work, CPU cost retention, bounded retries, lost leases,
crash-promoted output revalidation, no duplicate settlement, owner isolation,
If-Match/revision conflicts, prepaid/paid edits, refund revocation, cleanup, budget
fail-closed behavior and separate globally serialized render/AI claims.

Ignored evidence remains in `var/phase5-verification/`:
linux-final.log, pytest.xml, gate-status.json, render-smoke-final.log,
concurrent-render-smoke.log, ai-regression-smoke.log, ingestion-regression-smoke.log,
schema-drift.log, process-boundary.log and runtime-match.log (source hash manifest).
Prior Phase 1–4 evidence remains preserved. The existing stopped Phase 4 disposable
Compose project/network/DB volumes were reused with the Phase 5 override; no
unrelated Docker project was changed. Only verification services are stopped after
checks; their volumes and databases remain for inspection.

Actual local demo artifacts, excluded from Git: `D:\zoclip\var\phase5-verification\demo.mp4`,
`edited.mp4`, `preview.png`. These came from the authenticated end-to-end simulator
pipeline, not an invented URL. The preview was visually inspected: English wrapping,
outline contrast, safe placement and current-word yellow highlight are visible.

## Reproduce the gate

Use only the disposable project and `.env.example` placeholders. Prepare the
isolated CA as documented in PHASE4_VERIFICATION.md if it is absent. Keep that
internal fixture network isolated; these overrides are not deployment settings.

```powershell
docker build --tag zoclip-phase5:verify .
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase5-test.yaml config --quiet
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase5-test.yaml up --no-build --detach --wait --wait-timeout 180
```

Create `zoclip_phase5_linux_test` only if absent, in this disposable PostgreSQL.
Do not downgrade a populated database to rerun tests; use a fresh `_test` database.

```powershell
docker exec zoclip-phase4-verify-db-1 psql -U zoclip -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE zoclip_phase5_linux_test'
docker compose --project-name zoclip-phase4-verify --env-file .env.example -f compose.yaml -f compose.phase5-test.yaml run --rm --no-deps --user 0 -v D:/zoclip:/workspace -w /workspace -e TEST_DATABASE_URL=postgresql+psycopg://zoclip:CHANGE_ME@db:5432/zoclip_phase5_linux_test -e TEST_REDIS_URL=redis://redis:6379/15 api python scripts/verify_phase5.py
```

With that same Compose prefix, execute on api: `python scripts/container_smoke.py`,
`alembic check`, `python /verify/ai_smoke.py` with ZOCLIP_AI_SIMULATOR_SMOKE=1,
and `python /verify/render_smoke.py` with that opt-in plus
ZOCLIP_RENDER_SIMULATOR_SMOKE=1. The render smoke also tests simultaneous requests.
Run `scripts/ingestion_smoke.py` with the existing isolated HTTPS opt-ins from
PHASE4_VERIFICATION.md. Mount the repo read-only and run scripts/verify_runtime.py
inside a final-image API container; run scripts/render_boundary_smoke.py in a
network-disabled Linux container with `--init`. No live provider opt-in is used.

The FFmpeg/font base was built once; final review added Linux parent-death fencing,
then rebuilt only cached application layers and repeated the affected render smoke.
The full 275-test suite exercises the final source, including its bounded child
runner; installed runtime source equality was checked separately. Final lint/type
checks include the additional process-boundary smoke script and concurrent request
verification. Expensive full Docker suites were not rerun after small edits.

## Remaining acceptance boundaries

Real provider accounts/models/rates and useful real-world suggestions remain
unverified as explicitly required by the no-paid-call instruction. Face detection
is sampled frontal Haar focus, not active-speaker tracking; positive real-face
accuracy, rapid motion/multiple speakers and subjective Urdu/emoji shaping require
representative visual QA. Audio/video tolerance is 100ms with frame/codec quantization.
CPU/retention accounting is conservative on lost workers, Windows and projected TTL;
it is not an invoice reconciliation claim. Prepaid edits are capped and restored
on failed exports; a refunded original cannot fund them.

Opt-in 10/30/60/120-minute benchmark tooling is provided, not run. No throughput,
4vCPU VPS capacity, Ubuntu-host deployment, backups/restores, off-server media
recovery, legal retention approval or remote CI result is claimed. Docker uses the
repository's Python 3.12 Debian image; Ubuntu 24.04 host acceptance is still separate.
See RENDERING_HANDOFF.md for resource/configuration limits and API contracts.
