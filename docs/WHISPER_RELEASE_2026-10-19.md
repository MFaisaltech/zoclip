# Local Whisper staging verification — 2026-10-19

Default: faster-whisper **1.2.1**, small/cpu/int8, VAD/word timestamps enabled.
PyAV **17.1.0** is pinned: newer PyAV removed an argument used by faster-whisper.
Deepgram remains an inactive explicit fallback. No paid calls, public activation,
frontend changes, customer financial changes or applied CostRates.

| Requirement | Evidence |
|---|---|
| Adapter/TranscriptData | Fake-model tests, real PCM decoder and actual local inference; selection.py/schemas.py unchanged |
| Gemini/Deepgram | Original HTTPProviders, gemini_body and paid_request ASTs unchanged; explicit fallback selection without HTTP |
| Offline Docker model | Four SHA256-verified files at immutable revision 536b0662742c02347bc0e980a01041f333bce120; 486212372 bytes; no CUDA packages |
| Concurrency | One RQ AI worker, shared-volume OS lock, two native threads, 2 CPU/2560 MiB; API concurrency 32 unchanged |
| Final focused tests | **31 passed, zero failures/skips**, disposable PostgreSQL, real PCM decoder, fake inference/Gemini, receipt recovery and breaker cases |
| Local full checkpoint | **633 passed, 84 skipped, zero failures**, 501.49s; final focused tests followed decoder/alignment fixes |
| Static/API checks | Ruff check/format, mypy 83 modules, generated OpenAPI unchanged; diff and secret checks |
| Pushed-commit CI | GitHub Actions repeats the complete Linux suite and container health/ingestion smokes; final outcome is included in the delivery handoff |

Native alignment emitted one zero-length token. Its original text is joined to a
neighboring positive interval containing its timestamp; no time is fabricated or
text dropped. Unanchored tokens fail closed. Real decoder and alignment regressions
cover the problems caught by actual acceptance. ONNX telemetry is disabled.

## Final immutable-image benchmark

Video **9cced2b6-cf08-410c-b653-318eef1dc5fe**, SHA256
`4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80`.
Video 25.170s (rounded 26s); extracted PCM **25.14725s**.
Cold transcription including lazy model/library load: **20.70033s wall**,
**39.01076 CPU seconds**, **661.30469 MiB peak process RSS**, measured with Linux
getrusage. Container startup and preceding FFmpeg extraction are excluded.

Result: **98 timed caption groups**, preserving 99 native tokens; first start 0,
last end 25.02; valid confidence/speaker0; unchanged selection.transcript accepted
the body as TranscriptData. This is contract/timeline verification, not a human
word-error-rate benchmark. Transcript SHA256:
`f82481027b02235cfdddcfdf3813fb6ffd10e86537f10ee95308c2146ca07d2a`.

The UID10001 container used a read-only root/source volume, network `none`, no DB
or provider credentials, 2 CPUs/2560 MiB and a Python network audit guard. All model
hashes matched. Zero Deepgram/Gemini calls, generated clips, AI job dispatches,
credits or entitlement changes. The separate paid-test entitlement was unused.

## Deployment, protection and recovery

Release **staging-20261019-whisper6**, `/opt/zoclip-private`.
Image:
`zoclip-private-app@sha256:2e421e33f1406e0b68ee7849c01db3054d49e2d2c0d5bcc10119c1b498d0f131`.
Migration **e7319c2b504a** only widens the AI-request provider CHECK. Existing rows
matched before/after migration except the necessary Alembic version receipt;
all rows matched from post-migration through rollout. No balances, catalog,
credits, uploads or retained media changed.

Quiesced encrypted backup **20261018T211309-b0751db0.json**, manifest SHA256
`2354583426de7c1c5f1a641e3d86d4610744220296f13db13811546eb1e35dab`:
copied off-server; DB/media authenticated through EOF; PostgreSQL archive validated;
both retained media hashes compared. Recovery key stayed local; no plaintext
backup or overwrite restore. Both retained media files remain unchanged.

Seven healthy services: API, AI worker, render worker, maintenance, proxy,
PostgreSQL and Redis. Worker restart verifies identical offline model assets and
all service health. API stays VPN-only, public 18443/18444/5432/6379 blocked,
Vercel production/deployment URLs protected, anonymous media/account 401 and
docs/admin monitoring 404. Read-only containers, capabilities, networks, bindings,
closed public AI/payments/trials/signup/email and absent provider keys verified.

The original four-file operator and USD 0.10 entitlement independently reload as
PREPARED/unapproved, dispatch 0/committed 0. Original one-Deepgram/one-Gemini/one-clip/
zero-paid-retry policy remains unchanged. No approval was granted.

Primary rollback: explicit `TRANSCRIPTION_PROVIDER=deepgram`, recreate affected
containers, verify selection without provider calls. Prior code image retained:
`zoclip-private-app@sha256:a3a5763481d5304becb0685a5394f286ff7237d8c1c2427ccfbb5f581628a851`
with release staging-20261018-security1. Widened CHECK is backward-compatible;
do not downgrade or erase local history. See [operating guide](LOCAL_WHISPER.md).

Security comparison found no new HIGH/CRITICAL identities or fixable HIGH/CRITICAL
findings. Existing Debian backlog remains **207 HIGH / 1 CRITICAL**, not a clean
security or public-launch claim. Private receipts/manifests/logs stay in ignored
`var/whisper-20261019` and root-only staging build evidence.

## Unapplied cost proposal and limits

Propose USD0.000005/CPU-second, maximum 1320 CPU seconds/USD 0.006600 per bounded
work horse. **Not installed or approved.** See [allocation and future metering
requirements](WHISPER_COST_PROPOSAL.md). Prices, credits and current conservative
duration quotes/spending controls are unchanged.

| Source | Projected wall | Projected CPU seconds | Proposed allocation | Temporary PCM |
|---|---:|---:|---:|---:|
| 5 minutes | 246.95s | 465.39 | USD0.002327 | 9.16 MiB |
| 30 minutes | 1481.70s | 2792.33 | USD0.013962 | 54.93 MiB |
| 120 minutes | 5926.79s | 11169.31 | USD0.055847 | 219.73 MiB |

These are linear projections, **not long-source benchmarks**. The ratio suggests
about 73 source minutes/hour dedicated throughput before extraction, rendering,
queueing and contention. 30/120-minute projections exceed the existing 300s segment/
660s RQ bounds; completion cannot be promised. Keep failure limits and accurate
quotes. Long-source capacity requires separate measured work. Local transcription
removes Deepgram audio egress/invoice, while source transfer, Gemini transcript
traffic and existing VPS/memory/storage costs remain.

## Exact changed files

- `.env.example`, `Dockerfile`, `compose.yaml`, `deploy/compose.yaml`
- `pyproject.toml`, `uv.lock`
- `src/zoclip/ai/providers.py`, `src/zoclip/ai/worker.py`, `src/zoclip/ai/models.py`
- `src/zoclip/core/config.py`, `src/zoclip/ops/health.py`
- `alembic/versions/e7319c2b504a_local_whisper_requests.py`
- `scripts/download_whisper_model.py`
- `tests/test_local_whisper.py`, `tests/test_whisper_worker.py`, `tests/test_ai.py`
- `docs/AI_HANDOFF.md`, `docs/DECISIONS.md`, `docs/DEPLOY_CONTABO.md`
- `docs/IMPLEMENTATION_STATUS.md`, `docs/LOCAL_WHISPER.md`
- `docs/WHISPER_COST_PROPOSAL.md`, `docs/WHISPER_RELEASE_2026-10-19.md`
