# Synthetic capacity acceptance — 2026-10-20

Creator PKR 2,000 / 3,700 credits and Pro PKR 5,000 / 9,500 credits remain **inactive**. No deployment was performed. Continue from backend `920322d` and frontend `a9105df`; existing catalog, trial configuration, credits, quote rules, CostRates and customer records were preserved.

## Actual runs

These are synthetic infrastructure results on the existing 2-vCPU / approximately 8-GB VPS: repeated 30-second 1080p motion, locally generated Microsoft David speech, H.264 at 2.5 Mbps and AAC at 96 kbps. Files were 99,838,604 / 598,970,263 / 2,395,835,273 bytes. The final two-hour fixture is 7,199.931 seconds, within the unchanged limit. Disk was checked before generation; stream copying avoided unnecessary multi-hour encoding.

| Source | HTTP upload | Validate | Extract | Whisper | Captioned render | Upload to terminal | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| 5 min | 2.98s | 1.87s | 6.75s | 179.79s | 16.51s | **210.51s** | Completed; one selected clip, 5,427,380 bytes |
| 30 min | 13.78s | 10.69s | 37.69s | 323.52s, failed | Not reached | **386.49s** | Local ProviderFailure; credits released |
| 120 min | 59.77s | 21.33s | 0.84s, failed | Not reached | Not reached | **82.72s** | FFmpeg thread creation failed; credits released |

Authenticated chunked uploads used the actual ASGI app, PostgreSQL, Redis/RQ, production extraction, faster-whisper, clip selection, caption rendering and local storage in an isolated fixture environment. Upload times exclude WAN transport. Gemini was mocked and all real provider HTTP dispatch was forbidden. No Gemini or Deepgram calls occurred. Mocked Gemini, selection and persistence are included in processing totals; their individual latency was not instrumented. This does not validate natural footage, multilingual accuracy, highlight quality, real provider latency or paid token usage.

The five-minute transcription overlapped one 90-second captioned render: render took 67.03s and produced 15,592,563 bytes. Only one transcription and one render ran. CPU seconds were 10.76 extraction, 421.02 transcription including overlapping work, and 35.99 selected rendering; overlapping counters must not be added. The thirty-minute extraction/transcription used 62.24 / 608.56 CPU seconds. Per-phase counters are in the [JSON evidence](evidence/synthetic-capacity-20261020.json).

Thirty-minute process peak RSS reached 2,406,720 KiB (approximately 2.30 GiB). The combined 4.5-GiB controller cgroup reached its 4,831,838,208-byte peak, including file cache. Host CPU peaked at 99.52%; minimum sampled available host RAM was 4,434,685,952 bytes. Sampling gaps across controller recovery mean these samples are not a continuous worst-case guarantee. Disk was observed as low as 55,447,379,968 bytes after the two-hour run; the sampled series alone missed that low point. Fixture materialized storage was 3,100,071,520 bytes.

## Failure diagnosis and smallest fixes

The original two-hour extractor independently reproduced `pthread_create() failed` under unchanged CPU/address-space/file limits. Adding only `-filter_threads 1` succeeded in **56.51s**, 95.33 CPU seconds, under those same limits. That bounded-filter fix is included in source and regression-tested; it is not deployed.

An additional two-hour transcription of that successfully extracted audio ran with the actual AI worker's 2 CPUs and 2,560-MiB limit, network disabled. Docker reported **OOMKilled**, exit 137, after **46.75s**. This is a separate diagnostic, not a successful replacement pipeline run. Increasing a timeout alone cannot solve that memory failure. The thirty-minute run failed after 323.52s around the configured 300-second iteration guard; its original inner exception was not retained, so the precise branch is unproven. RQ's 660-second deadline was not exceeded by the normal terminal runs.

The smallest implementation path is bounded audio chunking with durable transcription checkpoints, explicit per-chunk memory/time limits and recovery, followed by fresh long-duration acceptance. A larger worker alone would also need deadline and throughput validation. No timeout, memory guard or credit allowance was silently relaxed.

## Capacity and customers

**No safe whole-catalog jobs/month figure is certified**, because both long-duration cases failed. For five-minute synthetic jobs only, the conservative projection is **1,128 jobs/month**. Worker time alone projects 3,866; seven-day storage binds first. Assumptions: 50% usable monthly time, 25% retry-work provision, three 90-second output renders plus one edit render, 162,208,856 retained bytes/job, a 40-GiB retained pool minus 229,098,014 existing bytes, and evenly distributed seven-day expiry. Four full renders per job are a projection from the measured render, not four observed outputs. Bursts can admit fewer jobs.

| Customers, near-equal Creator/Pro mix | Low 10% redemption | Average 35% | High 100% |
|---|---:|---:|---:|
| 20 | 210 jobs: fits projection | 760: fits | 2,190: exceeds |
| 35 | 363: fits | 1,313: exceeds | 3,784: exceeds |
| 50 | 525: fits | 1,900: exceeds | 5,475: exceeds |

Thus **20–50 customers are not supportable at guaranteed full redemption**. Even assuming only short jobs, average use exceeds projected storage capacity at 35–50 customers. At 50 full-redemption customers the modeled retained footprint is approximately 193 GiB before scratch/headroom; worker demand also exceeds the conservative worker allowance. Keep acquisition/activation gated until measured admission capacity supports promised redemption, or provision additional storage and compute. Credits remain 3,700 / 9,500.

Existing safeguards remain: pending queue 10, per-user active job 1, 650 daily credits, 20-GiB free-space headroom and atomic storage reservations. A daily credit ceiling is not a monthly commercial capacity guarantee. Measured SQL acceptance-to-claim samples were 0.016–0.219s with one job at a time; this is not a 50-customer load test. Existing admission/deadline regressions passed. Disposable expiry simulation deleted one source, repeat cleanup deleted zero, and ledger/balances stayed unchanged. Failures released exactly once; recovered controllers reused terminal results without reexecuting completed jobs. A five-minute deliverable settled 60 credits; failed 30/120-minute requests released 158/608 credits.

## Financial gate and preservation

Existing 60% safeguards were preserved. A conditional short-job sensitivity uses the real fixture's admission envelope of 9,831 Gemini input / 2,048 output units, never the mock's fictional receipt tokens or CostRates. At assumed $0.25/M input and $1.50/M output, $6 VPS plus $6 monthly provision once, a provisional 2% fee and the previously dated 277.0572 PKR/USD reference, modeled margins are 87.26–95.53%. At FX 300 / fee 8%, the minimum is 80.37%. These are assumptions, not freshly verified provider/gateway prices or paid invoices; included bandwidth is conditional. They do not establish a whole-plan financial pass or override failed technical/capacity acceptance.

Unchanged quotes for three outputs and one edit are 60 / 158 / 608 credits for 5 / 30 / 120 minutes. Creator and Pro therefore allow at most 61 / 158 minimum-price jobs; output counts remain conditional on selection, duration and actual deliverables. No pricing cards or active catalog changed because activation failed.

After removing all ten task containers, their internal network, fixture DB/Redis and generated remote media, seven staging services were healthy. Thirteen live table fingerprints, both retained source hashes and the deployed image were unchanged. Whisper remains default; Deepgram inactive; public AI/payments off; trial configuration unchanged. TLS health was 200, anonymous resources 401, docs/admin 404, public API/DB/Redis ports blocked, and both checked frontend URLs redirected to Vercel protection. Free disk returned to 64,769,167,360 bytes. No paid calls or live ledger changes occurred.

No rollout was attempted, so a fresh encrypted-backup/restore and rollback gate was not executed or claimed. The existing immutable staging image remains in place. That gate is still required before any future deployment, including the extraction fix.

## Verification and reproducibility

- Eighteen focused backend capacity/catalog regressions passed, then ten audio/Whisper/report regressions passed after the extractor fix, using disposable PostgreSQL 17 / Redis. Five final model and checked-in evidence replay tests also passed.
- Fifty-five frontend API tests passed at unchanged `a9105df`; prior build/typecheck/browser evidence remains applicable to unchanged frontend code.
- Ruff passed; mypy checked all 83 source files successfully.
- Generate speech with `scripts/generate_capacity_speech.ps1`, then motion fixtures with `scripts/generate_capacity_media.py`. The acceptance controller `scripts/synthetic_pipeline_acceptance.py` requires explicit opt-in, a fresh owned directory, internal-only Docker services and exact disposable database host/name. It must never receive deployment credentials. Fixture CostRates and mock tokens are fictional accounting scaffolding.
- Replay the model with `python scripts/synthetic_capacity_report.py docs/evidence/synthetic-capacity-20261020.json`.

Outcome: **Creator/Pro staging activation NO; deployment withheld**. Long-video ASR memory/deadline acceptance and promised-redemption capacity are the blockers. Backend changes are evidence, bounded extraction and reproducible test tooling; frontend remains unchanged.
