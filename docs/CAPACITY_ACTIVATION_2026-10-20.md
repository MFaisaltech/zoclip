# Capacity acceptance and two-plan activation result

**NOT ACTIVATED.** Owner-selected Creator PKR2,000/3,700 credits and Pro
PKR5,000/9,500 credits remain the exact two paid targets in the inactive catalog.
The existing active catalog and dashboard/API purchase terms are unchanged.
The owner explicitly required leaving them unchanged if any activation condition
failed. Representative pipeline/capacity and rollout acceptance have not passed.

## Requirement results

| Requirement | Result |
|---|---|
| Creator PKR2,000 /3,700 credits | Prepared in existing inactive proposal;61 five-minute jobs, up to183 conditional initial clips |
| Pro PKR5,000 /9,500 credits | Prepared in existing inactive proposal;158 five-minute jobs, up to474 conditional initial clips |
| Measured local processing capacity | Short-source diagnostic passed;5/30/120min media unavailable, monthly throughput unverified |
| Gemini mocked integration | Real prompt/chunk/request-envelope and selection validation; deterministic candidate; no remote inference |
|60% margin validation | Conditional included-cost projection passes; high-redemption single-VPS capacity not established |
| Queue and concurrency safeguards | Existing limits retained; new PostgreSQL tests verify queue-full rollback and separate one-AI/one-render claim fences |
| Backend tests |283 passed/2 skipped initially; additional13 passed with disposable PostgreSQL/Redis, including the previously skipped RQ transport test |
| Frontend tests |55 API tests passed; typecheck, lint and generated pricing checks passed; browser/build results below |
| Protected staging activation | BLOCKED; no catalog install or deployment |
| Seven-service health | All seven healthy before and after diagnostic |
| Data and balance preservation |13 table fingerprints match; both retained files match their existing hashes; image unchanged |
| Rollback readiness | Existing image/rollback retained; no rollout, new backup or restore/rollback rehearsal performed |

No subscription, new credit grant, wallet conversion, rate change, quote change,
provider activation, Whisper modification or automatic VPS upgrade. Trial terms,
eligibility and abuse protections remain unchanged. Historical orders and plan
versions were not rewritten; existing two-plan fixture tests verify their
preservation and grant idempotency in disposable databases.

## Actual authorized staging diagnostic

Reused deployed immutable image
`sha256:2e421e33f1406e0b68ee7849c01db3054d49e2d2c0d5bcc10119c1b498d0f131`.
One extra temporary container: network none, no secrets/DB/Redis, non-root,
read-only root and source volume,2CPUs/2560MiB,512MiB temporary filesystem,
capabilities dropped. Existing workers had no active jobs. Container removed
itself; temporary outputs never entered the customer media/DB.

Staging contains two copies of the same25.170s 2160x3840 video,114,549,007 bytes.
Extracted PCM duration25.14725s. Local files are26.703/26.735s; neither is a
representative five-minute input. No repeated/looped/synthetic speech was
presented as a longer benchmark. The available source yielded98 timed word
groups and **one** valid mock-selected highlight, despite requesting up to3.
The rerender reused the same preferences/transcript as an edit-path workload;
it is not an additional promised highlight or an editor API acceptance test.

| Measured local phase | Wall seconds | CPU seconds |
|---|---:|---:|
|Copy into disposable storage (not HTTP upload)|0.368|0.368|
|Production FFmpeg audio extraction|0.707|0.928|
|Cold local faster-whisper|28.159|45.423|
|Mock selection validation|0.000078|0.000087|
|Production tracked/captioned render + output validation|56.536|89.776|
|Same-source rerender + output validation|52.414|82.387|
|Two local file reads (not HTTP downloads)|0.017|0.017|
|Total measured phase work|138.201|218.899|

Process cumulative peak RSS **659.63MiB**. Child RSS is a cumulative getrusage
high-water mark and may inherit the parent's fork footprint; do not add peaks
or claim this is simultaneous host/container peak memory. Phase-boundary files
reached124,673,427 bytes; temporary tracking/encoder scratch peaks were not
sampled. Each encoded output4,659,815 bytes; both validated720x1280 H264/AAC,
timing and full decode through the production render engine. Separate cancellation
fixture stopped a renderer via its heartbeat. Real failure/retry frequencies,
queue wait, HTTP upload/download throughput and provider latency are **unmeasured**.

Gemini: one serialized mock request,3,596 input admission units and2,048 maximum
output units. These are byte-bound budget quantities, not measured billed tokens.
Using the previously reviewed standard text rates, that request's envelope is
$0.003971, not an actual invoice. Selection quality, thinking-token usage and
real-provider latency remain unverified. No paid Gemini/Deepgram requests ran;
no paid acceptance approval is needed until the local blockers are resolved.

## Capacity and fair processing policy

Maximum configured heavy concurrency remains **one Whisper transcription and
one FFmpeg render**. They can occupy separate workers; simultaneous peak behavior
has not been benchmarked, so this is configuration, not a newly certified safe
combined load. Shared-volume Whisper locking excludes duplicate inference;
PostgreSQL claim fencing excludes extra AI/render claims even with extra workers.
FFmpeg has two threads, bounded subprocess CPU/output/deadlines and process-tree
cancellation. Container CPU/RAM/pid limits remain in place; no new arbitrary
CPU-load or memory rejection threshold was introduced without measurement.
Admission during CPU/RAM pressure beyond these hard limits is not certified.

Existing fair gates: one processing job/account,10 queued jobs globally,
one initial render worker,40GiB retained commitments,>=20GiB free headroom,
atomic source/scratch/output reservations,650 daily credits and the proposal's
3,700/9,500 monthly credit ceilings. Queue-full returns429/Retry-After60;
storage-full507. Transaction rollback preserves the wallet on rejected processing.
Final failure/cancellation releases a hold once; partial/unknown provider outcomes
retain exposure and stop blind paid retries. No separate charge for infrastructure
retry. Existing credits remain on the ledger; however30-day access plus persistent
capacity rejection can prevent timely use. An explicit reviewed extension/retry
policy would be needed before sale; none was silently implemented.

New **local, undeployed** monitoring adds authoritative queued/running counts,
oldest queued age, running heartbeat age, hourly failures and terminal counts.
This covers already-dispatched RQ backlog, which outbox-age alone misses.
Existing monitor retains disk, budget, provider exposure and failure alerts.
No public API schema, migration, dependency or environment setting changed.

There is **no measured monthly throughput range**. Prior planning range968–2,165
jobs/month depends on assumed75MB five-minute sources and10MB outputs, uniform
retention and worker utilization; the higher bound is not supported by this
4K source. At this sample's bitrate, a five-minute source extrapolates to~1.37GB;
with seven-day retention the40GiB retained pool projects only~133–134 jobs/month
before scratch/bursts, depending on rendered revisions. This is a sensitivity,
not representative demand or a new product restriction. Transcription scales to
~336s/five minutes in this cold short-sample extrapolation, exceeding the300s
segment deadline; cold overhead and speech density prevent treating that as a
measured five-minute failure.30/120min remain untested and suspect under the
unchanged660s RQ/300s transcription bounds.

20/35/50 customers at5/20/60 jobs each means100–3,000 jobs/month; selling credits
does not eliminate that workload. Original full grants afford1,220–3,050 Creator
jobs or3,160–7,900 Pro jobs across those customer counts. The current evidence
does not establish that this host can satisfy those grants within acceptable
queues/storage. Rejecting excess work safely protects accounting, not delivery
of purchased value. No unlimited or immediate processing claim is supportable.

Financially, retain the owner assumptions ($6 upper VPS,20–50 customers,2% fee,
default Deepgram zero) and [final reproducible review](FINAL_PRICING_REVIEW_2026-10-20.md).
Its included-cost full five-minute redemption margins are~80%/90%, before
unpriced taxes/labor and subject to reserve assumptions. Funding hypothetical
capacity still clears60% in that model, but the scaling/data-placement mechanism
is not implemented, and traffic/backup-overage scenarios can fail60%. Neither
credits nor CostRates were reduced to manufacture a pass.

## Smallest safe next changes and release conditions

1. Provide actual authorized5-minute,30-minute and120-minute speech/video samples
   in the intended bitrate/language mix. Run the committed opt-in diagnostic,
   then isolated real RQ+mock-Gemini tests on disposable records with queued
   arrivals and simultaneous workers. Measure P50/P95 queue/processing time,
   retry/cancellation behavior, actual retained/scratch bytes and combined RAM.
2. If representative sources hit the unchanged deadlines, implement and review
   bounded transcription chunking/checkpoints or an explicit supported-duration
   policy. Do not simply relax kill limits or modify duration quotes.
3. Choose supported storage/retention/queue turnaround and, if needed, separately
   approve capacity expansion. The present evidence cannot justify activating
   full-redemption grants on one VPS; no automatic upgrade is authorized.
4. Recompute60% margin using the measured source/output mix, real included
   traffic/backup terms and provisional fee sensitivities. Then complete the
   build, recoverable off-server backup, schema/image compatibility, controlled
   catalog append/retirement and rollback checks before protected staging rollout.

Activation remains separate from payments/public AI/commercial launch. Merchant
acceptance, real account rates/Gemini end-to-end under separately authorized
spend, representative quality, SMTP/OAuth where enabled and existing security
backlog remain launch gates. No unapproved paid test was requested or run.

## Verification and changed files

Backend: fresh disposable PostgreSQL17, loopback SCRAM; financial concurrency,
quotes/plans, billing/refunds, media/storage, render/cancellation, Whisper mocks
and economics:283 passed/2 skipped (248.71s). Additional fresh PostgreSQL plus
disposable loopback Redis15:13 passed (10.69s; clean service shutdown), including real RQ outage/redelivery
and FFmpeg validation. One original skip was Redis and is covered by that rerun;
the Windows symlink-privilege test remains unrun locally. Prior Linux evidence
is historical, not a fresh pass. Ruff/format and mypy83 sources pass.

Frontend:55 API tests pass; TypeScript, lint and active/proposal generator
checks pass. Production build initially refused854.5MiB available RAM and then
1,300.1MiB against its unchanged1,536MiB start guard; no user processes were
killed to make space. Final build/browser status is recorded in the closeout.

Actual benchmark and preservation/access checks:
[machine-readable evidence](evidence/capacity-validation-20261020.json).
VPN health/ready200, unauthenticated account/media401, docs/admin404, public
18443/18444/5432/6379 blocked; domain and existing Vercel deployment redirect to
Vercel authentication. Seven services healthy, Whisper default, model blank,
Deepgram inactive, public AI/payment/trial grants off, circuit breaker on.
Thirteen table fingerprints and both media hashes match before/after, no customer
outputs/transcripts/provider usages were inserted. Existing image and schema
unchanged; no deployment, restore, catalog installation or backup interruption.

Exact backend changes:

- `scripts/benchmark_local_pipeline.py`: opt-in Linux offline diagnostic.
- `src/zoclip/ops/monitor.py`: private backlog/heartbeat/failure telemetry.
- `tests/test_capacity_acceptance.py`: PostgreSQL rejection/claim/telemetry tests.
- `docs/evidence/capacity-validation-20261020.json`: measured evidence and blockers.
- `docs/CAPACITY_ACTIVATION_2026-10-20.md`, `docs/IMPLEMENTATION_STATUS.md`,
  `docs/DECISIONS.md`, `docs/API_HANDOFF.md`: acceptance/status handoff.

Exact frontend changes: `scripts/generate-pricing-proposal.mjs`,
`lib/pricing-proposal.ts`, `components/pricing-proposal.tsx`,
`tests/browser/pricing-proposal.spec.ts`, `docs/CAPACITY_ACTIVATION_2026-10-20.md`.
The local preview remains behind `ZOCLIP_PRICING_PROPOSAL_PREVIEW=1`; it shows
the exact two owner targets, conditional jobs/clips and capacity caveats, with
no purchase actions. Default pricing and dashboard continue to use unchanged
active catalog/API data while activation is blocked.

## Final verification closeout

The production webpack build subsequently passed with reserved example origins,
preview enabled and the original RAM guard intact (minimum sampled free RAM
1,597MiB). Its successful build/typecheck does not deploy anything. Browser
checks against a temporary local production server: preview enabled3 passed/1
skipped (desktop/mobile proposal and unchanged active pricing/landing); preview
disabled1 passed/1 skipped, confirming default404. Skips deliberately cover
the opposite flag branch. Temporary server stopped after each run.

The initial browser harness was stopped before tests because its log directory
conflicted with Playwright output cleanup; the corrected harness separates logs
and output. The initial Redis test harness passed its cases but failed shutdown
cleanup; corrected harness reran13 cases with clean PostgreSQL/Redis shutdown
(10.69s). These setup/cleanup failures are not counted as test passes.

All requested verification possible with existing media is complete. Activation
remains blocked by the representative capacity/rollout conditions above. No
paid real-provider acceptance or new rollout/backup is claimed. Commits and
push verification are reported in the final handoff rather than embedding a
self-referencing commit hash in this file.
