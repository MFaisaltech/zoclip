# ZoClip unit economics audit

Audit date: **2026-10-20, Asia/Karachi**. Audit only; no pricing, CostRate,
quote, balance, provider behavior or deployment changes. Owner confirmed that the
actual invoice/currency, included traffic, overage/storage terms and unrelated
host workloads remain unknown. Missing evidence does not prevent this audit;
it prevents certification. The PKR 2,000/5,000 packages remain inactive.

## Findings and evidence standard

The old **USD 0.354475** five-minute estimate is reproducible, but is an allocated
stress scenario, not measured cash cost. It already excludes Deepgram from the
Whisper path. It combines hypothetical CPU/storage/transfer prices, a blanket 3x
multiplier and a second VPS allocation. There is a real overlap risk; the hosting
contract is unavailable, so a duplicate *invoice* cannot be established.

One five-minute/one-output planning scenario now separates **USD 0.0016 Gemini**,
**USD 0.132 hosting allocation**, and **USD 0.0334 single risk reserve**, totaling
**USD 0.1670**. The USD 0.132 uses the old unverified USD13.20/month reference and
100 five-minute-equivalent jobs/month. It is not a new external charge. At 500
equivalents/month the same modeled total is about USD 0.0350. Neither volume is
observed demand; neither amount is an actual verified full-job cost.

VERIFIED means code/measurement or directly checked public evidence; ESTIMATED
means explicit forecast/allocation; UNVERIFIED means material evidence absent;
NOT APPLICABLE means no such charge on the specified path. Public list rates are
verified as published, not as this account's invoice. The measured-cost scenario
has **unknown total cost and unknown certified credits**, never a fabricated zero.

Evidence:

- [Whisper release and benchmark](WHISPER_RELEASE_2026-10-19.md): packaged-image
  audio 25.14725s, wall 20.70032785s, CPU 39.010763s, peak 661.30 MiB. No new benchmark.
- [Fresh read-only staging snapshot](evidence/unit-economics-staging-20261020.json):
  2026-10-20 01:23:41 PKT; seven healthy services, zero AI requests/provider usages,
  transcripts/render outputs/orders/ledger rows; two completed validation jobs.
  Provider keys were not printed or used for provider requests. Standard app `gemini_model` is blank;
  analysis is not enabled. Any isolated operator's separately reviewed settings
  do not establish a configured commercial processing model or account price.
- [Reproducible simulation](evidence/unit-economics-simulation-20261020.json) and
  [read-only tool](../scripts/unit_economics_audit.py). No DB/env/network reads in
  the simulator, no provider calls or catalog installation. Synthetic text only.
- Public Gemini **3.1 Flash-Lite standard text**: USD0.25/M input, USD1.50/M output
  including thinking, checked 2026-10-20 at [Google](https://ai.google.dev/gemini-api/docs/pricing).
  This model is the pricing hypothesis, not a claim of active staging configuration.
- [SBP](https://www.sbp.org.pk/) displayed **2026-10-16** weighted-average offer
  **277.0572 PKR/USD**, M2M 276.9115, when checked 2026-10-20. Use the offer as a
  dated conversion reference, not a current card settlement quote. The legacy
  300 reference is a weaker-PKR sensitivity; card spreads/taxes remain unknown.

## Pipeline cost ledger

All local steps share the same VPS. CPU-seconds, RAM and disk are capacity usage,
not independent metered cash invoices unless a contract establishes one.

| Step / service | External API | Resource, time and footprint | Cost treatment / evidence |
|---|---|---|---|
| Upload/import: API, proxy, AI queue ingestion | NOT APPLICABLE to local validation; remote source may have its own terms | Streamed, ffprobe; <=4 GiB/source; max two ingestions, one/user; CPU/time per real source UNVERIFIED | Transfer/storage UNVERIFIED contract; input processing quota VERIFIED in `media/service.py`, `worker.py`, `probe.py` |
| Audio extraction: AI worker, FFmpeg | NOT APPLICABLE | Mono16kHz PCM16, 32,000 bytes/s; 9.16/54.93/219.73 MiB for 5/30/120min; 240MiB cap/300s deadline | Actual CPU/time UNVERIFIED; previous 2 CPU s/source minute ESTIMATED; temporary audio removed in `ai/worker.py` finally |
| Whisper: AI worker | VERIFIED zero Deepgram request/charge on local path | small/cpu/int8; 2 inference threads; benchmark above; one OS/process-serialized inference; worker 2CPU/2560MiB | Local compute matters; long-source time/CPU ESTIMATED, host allocation conditional; no standalone paid Whisper API |
| Gemini: AI worker HTTP | VERIFIED chargeable integration; actual bill UNVERIFIED | Compact transcript segments, 16kB/chunk, <=32 chunks, <=2048 output tokens/request, 120s provider timeout | List rates above; synthetic token forecasts below; no real usage receipts |
| Selection: AI worker Python | NOT APPLICABLE | Timestamp/overlap validation; CPU/RAM/time UNVERIFIED, bounded candidates/words | Included in shared host/uncertainty, no invented per-selection API charge |
| Reframe/render: render worker, OpenCV + FFmpeg | NOT APPLICABLE | Selected intervals, <=90s; 720x1280/30fps H264 CRF23 veryfast, maxrate4M, AAC128k; 2 threads; 240s wall/520 CPU-second admission envelope | Envelope VERIFIED, average CPU/time/RAM UNVERIFIED; 520 is NOT a measured average; captions/tracking/validation share budget |
| Captions: render worker ASS | NOT APPLICABLE | Existing timed words and optional edits; no re-transcription/LLM for a normal caption change | Included in render workload, not a second transcription charge; actual incremental work UNVERIFIED |
| Storage: local volume, DB and backup | Local storage API NOT APPLICABLE; external backup bill UNVERIFIED | <=256MiB/output, source-linked retention <=7d; originals <=4GiB; edited revisions also consume space | Count source once/source, renders/revisions once/output; local SSD included conditionally in host allocation, additional billed backup isolated in risk scenario |
| Downloads: API/proxy | NOT APPLICABLE provider inference | Authenticated completed exports streamed; repeated downloads consume egress and CPU | Contract/observed traffic UNVERIFIED. Three downloads is NOT enforced; no certified finite egress bound follows |
| Queues/retries: Redis/RQ/PostgreSQL | No extra queue-service invoice established | Durable outbox/leases, fsynced receipts, unknown spend retained; repeated failed work consumes resources | Included host and explicit risk scenario; no automatic blind paid retry |
| Payment: approved future merchant adapter | UNVERIFIED; currently disabled | Per-purchase processing/FX/refunds, no live orders | Scenario 5% + USD0.05/purchase; not a verified JazzCash fee; subtract ONCE at package revenue level |
| Logs/monitoring/operations: app/host | UNVERIFIED extra services/labor | Compose json-file rotation 10MB x3/container; DB metadata, health probes, backups and restore work | Local logging shares VPS; off-server copies, email, domain/frontend bills, support/tax/labor not verified or silently priced at zero |

Local retention and output bounds are configured limits. They are not proof of a
hosting/storage invoice or an average 90-second clip/256MiB output. Output size
depends on actual content/CRF. Original USD0.25GB/output is near a ceiling, not
observed average. There is no automatic full-source video re-encode.

## Reconstructing USD 0.354475

The old `scripts/two_plan_economics.py` is preserved, not corrected in place.
For five minutes/one output, before any gateway fee:

| Component | Base USD | Calculation / status |
|---|---:|---|
| Whisper CPU allocation | 0.00930776 | 39.010763/25.14725 x300 x0.00002; measured short CPU ratio, projected duration, unverified unit price |
| Audio extraction | 0.00020000 | 5 x2 CPU seconds x0.00002; estimated |
| FFmpeg render | 0.01040000 | 520 CPU seconds x0.00002; admission ceiling treated as average |
| Gemini | 0.00758400 | (16000+2048) x0.25/M +2048 x1.50/M; one full-chunk example reservation, not measured tokens |
| Original storage | 0.01166667 | 5 x0.033333GB/min x7days x0.01/GB-day; not a verified SSD invoice |
| Output storage | 0.02000000 | 2 GB-days x0.01; rounded retention allowance, not actual bytes |
| Downloads | 0.01500000 | 0.25GB x3 x0.02/GB; not observed or enforced |
| Base subtotal | **0.07415843** | These amounts are estimates/allocations |
| Blanket retry/operating increment | **0.14831685** | 2 x base, so the subtotal becomes 3x; retry and reserve are NOT separately identifiable |
| VPS fixed allocation | **0.13200000** | 13.20/100, both invoice and completed-job volume unverified |
| Total | **0.35447528** | Base x3 +VPS; rounded old report USD0.3545 |
| Deepgram | **0** | Not included on this local-transcription scenario |
| Payment | **Excluded** | Old package-ceiling formula subtracts fees once; not part of USD0.3545 |

The 3x factor triples storage, bandwidth and Gemini too. It does not describe the
actual retry policy or three paid requests. Operational reserve and retries cannot
be disentangled from that undocumented multiplier. No additional retry surcharge
should then be added on top. Unknown failures still need a provision; this audit
substitutes explicit 25%/50% scenarios, **not verified failure frequencies**.

The corrected *accounting structure* allocates one shared infrastructure pool
once; it does not claim proof of lower invoices. Remove a separate CPU/SSD/egress
cash line only conditionally on inclusion in that pool. Additional billed storage,
off-server backups, overage or another vendor remain separate when evidenced.
Longer sources and extra renders get larger shares of the same pool, rather than
the same USD0.132/job regardless of work. Do not add a separate `whisper_cpu` price
on top of this full allocation. Existing internal rates were not changed.

## Credit accounting audit

`credits/service.py:calculate` and versioned `ConsumptionRules` define the quote:

`max(60, ceil(source_seconds / 60)*5 + outputs*2 + edits*2)`

Current caption/reframe increments are zero. One credit is a versioned accounting
unit, not a fixed USD cost, source minute, clip or PKR. Its sale value depends on
package price/credit total; infrastructure expense is recorded separately in USD.

- Five minutes/one output: 25+2=27, raised to the **60 minimum**. Three outputs:
  25+6=31, still 60. Three outputs plus one edit: 33, still 60. This is not 60
  credits per clip. The minimum can cover ten minutes/three outputs/one edit:
  50+6+2=58 ->60. At 30/120min, one output is 152/602; three outputs 156/606.
- Seconds round UP once to whole minutes. The minimum masks short-job extras,
  making marginal render work cost zero additional credits until it is exceeded.
  A job with fewer selected clips is still settled at its accepted quoted amount;
  do not advertise guaranteed selected moments for every transcript.
- `media/service.py:process` compares quotes with validated source duration, locks
  the wallet, reserves once, then uses the outbox. Daily/monthly and concurrency
  quotas are separate from the wallet. Credits do not buy unlimited work.
- `rendering/worker.py` settles only after the selected outputs complete. Download
  also requires the job COMPLETED. Final failure/cancellation releases held credits
  via `media/service.py:terminate`/`credits/service.py:finish`; provider/failed CPU
  costs remain recorded. Release returns a hold, not a new grant. Staff refunds of
  a settlement are explicit/idempotent and are not currency refunds.
- Infrastructure retries do not create new customer deductions. Render has up to
  three transient attempts/output; paid 429 handling permits up to three *known
  rejection* requests/cache key with fresh budget admission. Unknown remote
  outcomes stop/reconcile receipts, never blindly repeat. One-shot live-test
  restrictions remain stricter. Failed jobs can be resubmitted by a customer, so
  successful-job credits alone do not bound all failed resource consumption.
- One prepaid edit is shared across the original job, not per clip. Successful/
  pending edits consume it; failures retain sunk cost but do not consume the
  deliverable allowance. A non-included rerender needs a fresh accepted one-output
  quote; no Gemini repeat merely to edit captions. The old ceiling evaluator
  omitted this prepaid edit; the new evaluator includes outputs+edits in render
  and retained-output resource estimates.
- No 60% contribution-margin constraint automatically ties a job to package
  revenue in runtime. USD budgets/attempt/disk gates prevent configured overspend,
  but cannot prove package profitability. `configured_rates`/`estimate` still
  require a **Deepgram-minute component even for Whisper**. That is an obsolete
  conservative admission estimate, NOT a Deepgram dispatch or invoice. Local
  Whisper does not create a paid SpendAttempt; authoritative Whisper metering and
  replacing this legacy envelope need separate reviewed work. Staging currently
  has no CostRates or policy and breaker ON, so paid admission remains closed.

The scale is partly duration-based but commercially chosen. Multiplying grants
by ten without changing quotes increases resource entitlements tenfold; multiplying
both grants and quote rules by ten changes display only. Any rescaling proposal
must version the unit/rules and API, preserve immutable old quotes/orders/ledger,
handle old and new wallets with an explicit conversion ledger and reconciliation,
and require owner approval. Do not rewrite history or silently revalue balances.

## VPS capacity and evidence gaps

Snapshot: four logical CPUs, 7.76GiB total RAM, **6.48GiB available**, no swap,
95.82GiB filesystem, **60.37GiB free**. Five-second host busy sample **8.17%**;
this is a momentary non-processing baseline, not a long-term idle average. Worker
resident memory was about 62MiB AI/64MiB render (model not doing inference).
Only seven ZoClip containers were observed; that does not exclude host processes,
another tenant/virtualization workload or unrelated monthly bills.

AI and render each allow 2CPU concurrently; API, PostgreSQL, Redis, proxy and
maintenance also run. Sum of limits exceeds four CPUs, so simultaneous maxima
contend. Container memory ceilings total about7.38GiB with little OS margin;
idle available RAM is not measured simultaneous-peak capacity. One AI worker,
one render worker and the host-wide Whisper lock stay unchanged. Up to 40GiB
retained commitments and >=20GiB free headroom are application capacity gates,
not guarantees of fit for arbitrary concurrent maximum inputs/scratch/revisions.

Linear short-benchmark projection: five-minute Whisper ~247s wall/465 CPU s;
30min ~1482s/2792 CPU s; 120min ~5927s/11169 CPU s. Cold-load overhead is scaled
too; speech density, language and contention change speed. These are NOT longer
benchmarks. The 300s local segment deadline/660s RQ workhorse remain unchanged;
30/120-minute completion is unverified and projected past these limits.

At uninterrupted dedicated benchmark speed the transcription-only upper projection
is ~14.6 five-minute sources/hour, ~350/day, ~10,500/30days at 24x7 operation.
An eight-hour/day illustration is ~117/day or ~3,500/month. Neither is a supported
service capacity or a sales target: render/ingestion, process startup per RQ
workhorse, failures, pauses, memory, user concurrency and available storage reduce
it. RQ forks a workhorse; PID-keyed model caching does not guarantee a warm model
across different jobs. There is no measured full-pipeline jobs/day/month value.

Needed: invoice and host-usage attribution; included GB/month and marginal egress;
representative extraction + Whisper + tracking + caption + encode + validation
CPU/wall/peak RAM/output bytes for 5/30/120min, cold/warm and simultaneous workers;
queue wait, P50/P95, failure/retry/no-suggestion rates, retained GB-days, download
bytes/count and backup growth over a meaningful period. First measure local-only
phases without paid calls; provider e2e requires separate explicit spend approval.
No production stress tests or new inference were performed in this audit.

## Gemini behavior and optimization proposals

No integration change. `selection.py` already discards duplicated unpunctuated
words/confidence/per-word speakers for analysis and uses compact timed segments.
Confidence/full word timestamps remain local for captions. Chunks overlap by
roughly one tenth of segments (at least one), so boundary text and instructions/
schema repeat. The whole transcript is not resent for each output or normal
editor rerender. Each chunk has its own durable cached response key; prompt/model/
request changes invalidate that key. Context caching/batch pricing is not used.

| Source | Synthetic requests | Forecast input/output tokens | Forecast USD | Actual-body admission USD |
|---|---:|---:|---:|---:|
| 5min | 1 | ~3,375 /512 | 0.00161 | 0.00645 |
| 30min | 5 | ~21,192 /2,560 | 0.00914 | 0.03655 |
| 120min | 17 | ~82,758 /8,704 | 0.03375 | 0.13498 |

Fixture: 180 seven-letter English words/minute, actual unchanged segment/chunk/
prompt/schema functions. Input forecast uses serialized bytes/4; output512/chunk
is a scenario, NOT tokenizer output or real consumption. Non-English/tokenizer/
thinking/metadata differences matter. Actual admission uses serialized UTF-8 bytes
**plus1024**, and full2048 output tokens. Receipts count all residual billed output
tokens including thoughts; no assumed free thinking or cache discounts.

The old32x(16000+2048) token envelope is only an example, not a proven serializer
bound: JSON transcript text escapes quotes/backslashes again inside the request.
The new risk scenario derives protocol bytes from the real empty request and
reserves twice chunk bytes plus that protocol; <=32 requests and2048 outputs each.
It is intentionally not an expected five-minute token bill. The exact serialized
request still controls every real paid admission; no fixed example replaces it.

Recommendations only: measure actual usage before reducing token ceilings; test
smaller structured candidate responses/metadata strings against selection quality;
evaluate overlap reduction and prompt/schema repetition, reuse successful cache
entries, and avoid unnecessary reanalysis of unchanged sources. Any model/prompt/
chunk/safety/token-limit change needs separate quality and budget review. Do not
assume free tier, new model discounts, batching or lower output limits are already
in use. Optimizing Gemini alone saves mills on the five-minute forecast; fixed
hosting utilization, rendered outputs/edits and failed work dominate this scenario.

Financial scenarios and conditional recommendations are in
[pricing simulation](ZOCLIP_PRICING_SIMULATION.md). No code outside read-only
tooling/tests/documentation was changed. Existing pricing, balances, backups,
VPN-only API, Vercel protection and public AI/payment restrictions remain in place.
