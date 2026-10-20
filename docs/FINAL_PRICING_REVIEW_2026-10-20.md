# Final owner-cost pricing review — inactive recommendation

**Decision:** retain **Creator PKR2,000 / 3,700 credits** and **Pro PKR5,000 /
9,500 credits** as the commercial target in the existing inactive proposal.
The owner-cost correction supports these allowances financially under the
included-hosting scenarios. It does **not** establish that one existing VPS can
deliver full redemption by 20–50 customers. Capacity expansion/measurement must
precede selling that entitlement; there is no activation approval in this review.
The previous 280/720 recommendation is superseded as a financial recommendation.

If the business must stay on exactly this VPS, without capacity expansion and
with up to 50 all-Pro full-redemption customers, a model-derived fallback is
**440/1,100 credits** (7/18 five-minute jobs; up to21/54 initial clips).
That is a capacity compromise, not the recommended value proposition. It also
is not certified under the slower conservative capacity case. Neither pair
changes the active catalog. There is no universally safe allocation without
specified workload, source sizes, traffic contract and queue service standard.

## Evidence and assumptions

Owner-provided: VPS about **USD5.30–6/month**, 20–50 paying customers/month,
local faster-whisper, inactive Deepgram fallback, provisional **2% payment fee**
and 60% contribution target. Model uses the upper USD6; this replaces the
outdated USD13.20 assumption. No assumed fixed merchant fee. The 2% is the
owner's Rs20/Rs1,000 planning estimate, not an authenticated JazzCash rate.

Measured, reused without rerunning: packaged Whisper small/cpu/int8 on two CPU
threads transcribed25.14725s in20.70032785s wall /39.010763 CPU seconds, peak
661.30MiB. [Release evidence](WHISPER_RELEASE_2026-10-19.md) and prior read-only
[snapshot](evidence/unit-economics-staging-20261020.json) establish the code and
host inventory, not commercial pipeline throughput. No fresh server inspection,
inference or paid request was performed. Latest prior audit: `6fcabea`.

Google's [official pricing](https://ai.google.dev/gemini-api/docs/pricing),
rechecked2026-10-20, still lists Gemini3.1 Flash-Lite standard text at
USD0.25/M input and USD1.50/M output including thinking. This is a hypothesis
for costing; the snapshot's application model is blank. Reuse the dated prior
audit FX **277.0572 PKR/USD (2026-10-16)**; fresh SBP retrieval failed, so this is
not a newly verified spot/card rate. No free-tier subsidy or caching discount.

All other numbers below are **projections**, not measured processing bills,
observed usage, verified merchant fees or guaranteed delivery capacity.

| Scenario | Monthly pool | Variable-cost reserve | Extra storage/transfer | Capacity assumption |
|---|---:|---:|---|---|
| A expected | $12 = $6 VPS + $6 operating/backup/upgrade provision |25%| Included locally/in host contract, conditional |50% of each worker's24x7 month usable |
| B high usage | $24 = $6 VPS + $18 provision |25%| Same conditional inclusion | Same capacity; heavier actual workloads |
| C conservative | $36 = $6 VPS + $30 provision |50%| Additional billed $0.02/source and per rendered revision |35% usable,1.25x slower |

The monthly provision is a budget assumption, not an actual vendor invoice or
an extra VPS already installed. Failed-job/retry reserve applies once to variable
costs; monthly infrastructure is paid once and capacity models include retry work.
No per-CPU-second cash bill is added for Whisper or FFmpeg. Included local SSD,
PostgreSQL/Redis/API/logging share that same pool. Separate billed backup/egress
is modeled only in C. A source is stored once; initial outputs and edit revisions
each consume storage/render capacity. Payment is deducted once from package revenue.
These are cash contribution projections after explicit operating provisions,
before unpriced owner labor, taxes, chargebacks and other unknown business expenses.

## Credits, jobs, clips and actual cost

Runtime rules are **unchanged**:
`max(60, ceil(source_seconds/60)*5 + outputs*2 + edits*2)`.
Five-minute one-output raw27 credits becomes60 because of the minimum; three
outputs raw31 also becomes60. Ten minutes/three outputs/one edit raw58 is60.
Thirty minutes/one output is152; two hours/one output602. Initial outputs<=3;
one prepaid edit is shared across the job, not one per initial clip. Normal
caption edits reuse the transcript; they require a render, not another Gemini call.

Issued credits are a prepaid allowance. Consumed credits are accepted quotes
settled on successful deliverables. A processing job transcribes/analyzes one
source and can produce multiple clips. Clip counts below are conditional on
valid selected moments and successful rendering. An edit produces a revised
output, not an additional promised highlight. Credits have no universal USD
exchange rate. Failed jobs release the hold but retain sunk infrastructure/API
costs, so credits alone cannot bound repeated failures or downloads.

`CostRate`/policy estimate still requires a Deepgram-minute component even on
the Whisper path; this legacy admission envelope is not a Deepgram invoice.
Default local Deepgram API cash cost is **$0**. No CostRates, quote engine,
provider, balance, timeout or completed Whisper implementation was changed.

The simulator reuses real quote/prompt/chunk code and synthetic180 words/minute.
Five-minute Gemini forecast is$0.001612,30min$0.009138,120min$0.033745;
512 output tokens/chunk and bytes/4 input forecast are assumptions. C uses the
actual serialized request's conservative admission token envelope instead.

At35 customers x20 homogeneous jobs/month, expected pool allocation is
$12/700=$0.017143/job. These are **alternative homogeneous-volume scenarios**,
not additive rows allocating the same pool several times within one mixed month:

| Source / initial outputs / edits | Credits | Gemini forecast | Total allocated USD | AI wall projection | Render service planning |
|---|---:|---:|---:|---:|---:|
|5min /1 /0|60|0.001612|0.019157|277s|260s|
|5min /3 /0|60|0.001612|0.019157|277s|780s|
|5min /3 /1|60|0.001612|0.019157|277s|1040s|
|30min /1 /0|152|0.009138|0.028565|1512s|260s|
|120min /1 /0|602|0.033745|0.059325|5957s|260s|

Equal cash totals for more local renders do not imply equal physical work:
the existing fixed host bill stays fixed until capacity must be increased.
Different workload mixes need the capacity calculation, not a fabricated local
metered invoice. AI wall adds30s/job for untimed extraction/startup/analysis;
render uses max(240s wall admission,520 CPU s/2 CPUs)=260s/render as a conservative
planning service time. Neither is a measured average.30/120min completion is
unverified and projects past unchanged300s transcription /660s RQ limits;
even10min local execution is not established. Accounting ceilings across these
durations are hypothetical obligations, not claims of supported completion.

## Capacity, storage and queue limits

One AI worker, one render worker, four shared CPUs remain the architecture.
Capacity takes the minimum of AI wall, render wall, total CPU and retained disk.
At50% usable time and25% retry allowance, CPU/worker projections before disk
are about**3,743 five-minute one-output jobs/month**,1,329 three-output jobs,
and996 three-output-plus-edit jobs. These are planning ceilings, not benchmarks.

Storage forecast:15MB/source minute,10MB/rendered file,7-day retention,
uniform arrivals;40GiB retained commitment gate, with>=20GiB disk headroom
maintained separately. It reduces the one-output illustration to about**2,165
jobs/month**, and ten-minute/three-output/edit to about**969**. These source/output
sizes are unmeasured; worst accepted4GiB sources plus256MiB/revision can fill
retained capacity after about8 jobs. Scratch, bursts and backup copies can reduce
usable space further. A finite monthly capacity cannot be certified from input
limits or download assumptions. See generated tables/artifact for exact floors.

Prior snapshot:7.76GiB RAM,6.48GiB available,60.37GiB disk free. Whisper's measured
661MiB process peak fits its2560MiB worker limit in the short isolated test;
simultaneous render/AI/DB peak is unmeasured. Container ceilings sum~7.38GiB,
leaving little OS margin at maxima. No OOM-free service guarantee follows.

Uniform medium workloads can fit the projected worker/disk envelope;60 jobs
per customer with3 outputs and1 edit exceed it in all20/35/50-customer scenarios.
An immediate50-job burst can put the last job behind~4.7h of one-output work or
~17.7h of four-render work with the retry allowance. These FIFO illustrations
are not latency percentiles; measured arrival/service distributions and an owner
queue-time standard are absent. More RAM or additional vCPUs do not automatically
increase the single serialized Whisper worker. Scaling means separately reviewed
worker/storage deployment and benchmarking, not silently raising concurrency.

## Conditional maxima and final comparison

Generated tables below report the exact simulation. Financial ceilings enumerate
1..120min,1..3 outputs,0..1 edit using the real quote. For each plan:

`floor((price/FX*(1-fee-0.60) - monthly_pool/customers) / worst_variable_USD_per_credit)`.

This is an upper bound under each scenario, never a recommendation to grant all
the financially cheap credits regardless of queue capacity. Pool is subtracted
once/customer; ceilings do not assume customers equal jobs. Single-host columns
assume all customers buy the named plan; joint balanced-mix ceilings explicitly
assume50:50 Creator/Pro and Pro=2.5x Creator. Neither mix is observed demand.
Discrete delivered-job counts floor the quote divisions; financial ceilings use
the stricter full-credit pro-rata inequality. Unspent credit breakage is not used
to prove full-redemption profitability.

The original allocations are sustainable **in the included-cost financial
projection**, and fit low/medium expected redemption. They do **not** fit a
single host at simultaneous full redemption. Supplemental billed traffic/storage
in C can also defeat the60% financial target. Thus "financially plausible" is
not an unconditional sustainability certification. Replacing3700/9500 with
280/720 solely because of the old USD0.3545/job estimate is not justified.

Scaling estimates in the artifact compute required host equivalents, then replace
the pool with **$6 x hosts + $6 monthly operating provision**, rather than adding
the old pool again. Full original redemptions require roughly2–9 host equivalents,
depending on plan/customer count and modeled disk, with projected margins still
above60% under included traffic. These are budget illustrations; horizontal
scaling/data placement are not implemented or authorized here, and a same-price
upgrade with proportional throughput is not an available verified offer.

## Reproduction and scope

From backend root:

```powershell
.venv/Scripts/python.exe -m scripts.final_pricing_review
.venv/Scripts/python.exe -m pytest tests/test_final_pricing_review.py tests/test_unit_economics_audit.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check scripts/final_pricing_review.py tests/test_final_pricing_review.py
.venv/Scripts/python.exe -m ruff format --check scripts/final_pricing_review.py tests/test_final_pricing_review.py
```

JSON replay is [saved here](evidence/final-pricing-review-20261020.json).
No database/environment/network reads, catalog installer, model inference or
provider dispatch in the new simulation. Review imports the existing pure quote
and synthetic forecast helpers. Old audit/simulation artifacts remain historical
reproducible evidence. Existing two-package proposal remains unapproved,
`release_status=proposal`, and `review_only=true`; free trial is unchanged.
No migration, configuration setting, frontend change, deployment, balance update,
JazzCash activation or public AI activation. Focused verification is recorded in
implementation status; full integration/model tests are outside this arithmetic
review and were not rerun.

Remaining activation evidence: included traffic/backup contract, real merchant
fees and FX/taxes, account/model rates, token receipts under separately approved
spend, representative local phase timings/languages/file sizes/retry rates,
simultaneous RAM/disk peaks, and acceptable queue performance. Retain3700/9500
for value while funding and validating capacity; do not sell unlimited processing
or promise a two-hour source completes on the current implementation.

## Generated numerical tables

Comparison basis: full five-minute redemption,3 initial outputs +1 edit/job;
20 customers, scenario B pool$24/month,2% payment fee; costs exclude the payment
fee while margins include it. These cash margins do not certify single-host capacity.

| Package | PKR | Credits | 5min jobs | Conditional clips | Cost USD/customer | Margin | Render hours/customer |
|---|---:|---:|---:|---:|---:|---:|---:|
|Old Starter|299|500|8|24|1.216|-14.7%|2.89|
|Old Creator|699|1300|21|63|1.242|48.8%|7.58|
|Old Pro|1299|2400|40|120|1.281|70.7%|14.44|
|Original Creator|2000|3700|61|183|1.323|79.7%|22.03|
|Original Pro|5000|9500|158|474|1.518|89.6%|57.06|
|Previous conservative Creator|2000|280|4|12|1.208|81.3%|1.44|
|Previous conservative Pro|5000|720|12|36|1.224|91.2%|4.33|
|Single-host fallback Creator|2000|440|7|21|1.214|81.2%|2.53|
|Single-host fallback Pro|5000|1100|18|54|1.236|91.1%|6.50|

| Customers | Workload | Jobs/customer | Jobs/month | Clips/month | AI hours | Render hours | Retained GB | Fits planning envelope |
|---:|---|---:|---:|---:|---:|---:|---:|---|
|20|low|5|100|100|9.6|9.0|2.0|True|
|20|medium|20|400|1200|38.5|108.3|9.8|True|
|20|high|60|1200|3600|218.3|433.3|53.2|False|
|35|low|5|175|175|16.8|15.8|3.5|True|
|35|medium|20|700|2100|67.3|189.6|17.1|True|
|35|high|60|2100|6300|382.0|758.3|93.1|False|
|50|low|5|250|250|24.0|22.6|5.0|True|
|50|medium|20|1000|3000|96.2|270.8|24.5|True|
|50|high|60|3000|9000|545.7|1083.3|133.0|False|

Low=5min/1output/0edit; medium=5min/3outputs/0edit; high=10min/3outputs/1edit.
High is a hypothetical accounting/capacity obligation; local10min completion is unverified.
Storage/traffic figures assume uniform arrivals and file sizes stated above.

| Scenario | Customers | Financial Creator max | Financial Pro max | All-one-plan host max per customer | Joint balanced Creator/Pro max |
|---|---:|---:|---:|---:|---|
|expected|20|26235|76605|2828|1616/4040|
|expected|35|29383|79753|1616|923/2308|
|expected|50|30642|81012|1131|646/1616|
|high_usage|20|18890|69260|2828|1616/4040|
|high_usage|35|25185|75556|1616|923/2308|
|high_usage|50|27704|78074|1131|646/1616|
|conservative|20|332|1785|1395|332/830|
|conservative|35|605|2058|797|455/1139|
|conservative|50|714|2167|558|319/797|

| Provisional fee | Financial Creator ceiling B50 | Financial Pro ceiling B50 |
|---:|---:|---:|
|2%|27704|78074|
|5%|25053|71447|
|8%|22402|64819|
|10%|20634|60400|

| Full original allocation | Customers | Projected host equivalents | Fleet + operations USD/month | Full-credit margin |
|---|---:|---:|---:|---:|
|creator|20|2|18|81.3%|
|pro|20|4|30|85.4%|
|creator|35|3|24|84.3%|
|pro|35|6|42|87.1%|
|creator|50|4|30|85.5%|
|pro|50|9|60|87.1%|
