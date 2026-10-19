# ZoClip pricing simulation and conditional recommendation

2026-10-20, Asia/Karachi. **Audit complete; allocations not certified or activated.**
Read with [cost/credit/capacity audit](ZOCLIP_UNIT_ECONOMICS_AUDIT.md) and
[machine-readable calculations](evidence/unit-economics-simulation-20261020.json).
Existing customer prices/credits, quotes, balances, spending controls and public
restrictions are unchanged. No deployment, payment onboarding or paid calls.

## Revenue, fees and margin definition

Creator PKR2,000 and Pro PKR5,000 are one-time prepaid package hypotheses. No
subscription. Retain trial protections. For comparison with the previous credit
ceiling calculator, preserve **60% of gross sale revenue after processing and
gateway costs**, a stricter test than60% of revenue *net* of payment fees. The
existing optional ops report uses a net-revenue denominator; neither formula is
an automatically enforced retail-price profitability gate. Do not equate them or
lower the60% target by changing denominators.

`G = price_PKR / FX`

`net = G*(1 - fee_fraction) - fixed_fee`

`allowable_processing_cost = max(0, net - 0.60*G)`

`credit_ceiling = floor(allowable_processing_cost / worst_cost_per_credit)`

Use SBP weighted-average **offer277.0572 PKR/USD, dated2026-10-16**, checked on
2026-10-20 at [SBP](https://www.sbp.org.pk/). It is a dated reference, not a verified
provider-card conversion. Previous300 remains a sensitivity, not an incorrect
arithmetic conversion. Example fees **5% +USD0.05/purchase**, account/merchant
terms unverified; no JazzCash fee/onboarding assertions. Fees are deducted once
per purchase, not again per job. Full consumption is assumed; do not depend on
unused credit balances or access expiry to make a margin.

| Plan | Gross USD | Net after example gateway | Maximum processing allocation at60% |
|---|---:|---:|---:|
| Creator | 7.22 | 6.81 | 2.48 |
| Pro |18.05 |17.09 | 6.27 |

Taxes, FX spread, refunds/chargebacks and operating labor remain unverified. This
is a conditional contribution test, not a net-profit forecast or a measured
expected customer mix. A business-level fixed-cost break-even test is separate.

## Three scenarios

**A: measured/verified evidence only.** Local benchmark CPU/wall/RAM and zero
Deepgram API charge on the Whisper path are known. Gemini public list rates are
known; actual account/model usage, render usage, hosting invoice and fees are
unknown. **Total cost, margin and sustainable credits are unavailable**. Do not
divide by the known zero external transcription charge to infer infinite credits.

**B: planning, with one shared infrastructure allocation.** Retain the historic
USD13.20/month *hypothesis*, not an invoice. Initially assume100 five-minute,
one-output **CPU-equivalent jobs/month**, not100 arbitrary jobs. Reference work:
`W5 = (39.010763/25.14725)*300 +520 +10 =995.39 CPU seconds`.
This uses a projected Whisper measurement and the existing render admission
ceiling; extraction10s is estimated. It is an allocation weight, not a measured
average job. For source minutes m, output count n and prepaid edit count e:

`W = (39.010763/25.14725)*60*m +520*(n+e) +2*m`

`hosting_share = (monthly_host_cost / monthly_reference_equivalents) * W/W5`

`B = (hosting_share + forecast_Gemini) *1.25`

Local CPU/RAM/SSD/ordinary transfer are conditionally included in the hosting pool;
there is no second CPU-second or local GB-day cash charge. This assumes included
capacity/traffic is sufficient. Additional invoice/backup cost cannot silently
be treated as included once discovered. The25% provision is a single explicit
failure/uncertainty scenario, not observed incidence or permission for paid retries.
Synthetic Gemini forecast uses actual compact-chunk code, estimated bytes/4 input
tokens and512 output tokens/chunk. This is not certified average tokenization.

**C: conservative risk scenario.** Same one-time hosting allocation; maximum32
Gemini chunks at conservative JSON serialization bounds and2048 output tokens
each (USD0.377176). Also assume *additional billed* copy retention: full4GiB source
plus256MiB per initial output/edit for7days at USD0.01/decimalGB-day, and three
downloads per output/edit at USD0.02/GB. These are supplemental service/overage
scenarios, not duplicate local SSD charges. Apply one50% risk provision. This is
not the expected five-minute bill and **not a hard global worst-case bound**:
download count and repeated failed submissions have no finite credit-derived cap,
contract prices are unknown and independent USD/disk gates may reject work.

| Source | Outputs | Quote | B marginal Gemini forecast | B allocated host | B total with reserve | C total with reserve |
|---|---:|---:|---:|---:|---:|---:|
| 5min |1|60|$0.0016|$0.1320|**$0.1670**|$1.2671|
| 5min |3|60|$0.0016|$0.2699|$0.3394|$1.5786|
|30min |1|152|$0.0091|$0.4472|**$0.5704**|$1.7399|
|30min |3|156|$0.0091|$0.5851|$0.7428|$2.0515|
|120min|1|602|$0.0337|$1.5820|**$2.0196**|$3.4420|
|120min|3|606|$0.0337|$1.7199|$2.1920|$3.7536|

No prepaid edits in these representative rows. The ceiling calculation includes
0/1 prepaid edit and1..3 initial outputs across1..120 whole minutes. Within each
rounded-up minute the quote/Whisper/source-storage model is monotone, so minute
endpoints cover this model. It does not establish codec/language/traffic bounds.
30/120min are accounting projections, **not verified completing jobs** under the
unchanged transcription/workhorse deadlines. One successful source does not
guarantee coherent moments, nor delivery of every requested clip.

### Conditional credit ceilings and outputs

| Scenario | Creator ceiling | Pro ceiling | Five-minute one-output jobs | Five-minute three-output clips |
|---|---:|---:|---:|---:|
| A, evidence only | unknown | unknown | unknown | unknown |
| B,100 reference equivalents |293|742|4 /12|12 /36|
| C, supplemental-cost risk |81|205|1 /3|3 /9|

Clip columns are Creator/Pro divisions of actual quoted credits, conditional on
successful selection/rendering. A third output does not incur another60 credits
when the minimum dominates; do not advertise4/12 as a universal clip allowance.
At the **B ceilings**, one-output 30min quotes afford1/4 jobs;120min0/1. At C
ceilings,30min0/1;120min0/0. The source-duration entitlement cannot override an
insufficient balance. Daily/monthly limits and execution capability still apply.

The binding B/C modeled cost-per-credit case is **ten minutes, three initial
outputs and one prepaid edit,60 credits**, rather than the representative
five-minute/one-output case. B allocates ~USD0.5065; C ~USD1.8290 to that case.
All ceilings are rounded down and tested with ceiling+1 against the60% inequality.
Pro has modestly better value/credit because a fixed fee is amortized over a
larger sale. This does not depend on changing internal CostRates.

### Sensitivity and recommendation

There is no verified volume forecast. Keep the100-reference-equivalent case for
comparison; explicitly show higher-utilization hypotheses rather than inventing
lower render benchmarks or cheaper provider rates:

| B monthly five-minute-equivalent workload | Creator ceiling | Pro ceiling | Five-minute one-output jobs |
|---|---:|---:|---:|
|100|293|742|4 /12|
|500|1,420|3,593|23 /59|
|1,000|2,731|6,912|45 /115|

An arbitrary long/multi-output job consumes several equivalents. These rows do
not claim100/500/1,000 real successful customers or jobs. Hosting is recovered
only if the assumed aggregate reference workload materializes. Lower demand
raises allocated cost, even when marginal provider cost is small. Increasing
equivalents cannot replace evidence of sufficient CPU/RAM/disk/queue capacity.
USD13.20/N refers to the whole assumed bill, so it must not be charged twice
through CPU/storage line items. Unknown backup/support bills would raise the pool.

**Recommendation for owner review, not activation:** validate invoice inclusion,
collect representative local telemetry and then review **Creator280 / Pro720**
as a rounded-down candidate for the B100 scenario. It gives4/12 five-minute
one-output jobs (or at most12/36 initial clips at three outputs/job), modeled
gross contribution margins about**61.6%/61.0%** on the binding usage. Pro gives
about2.9% better credits/PKR. These are accounting scenario results, not expected
profit or a guarantee. The generated automatic 60-credit-block candidate
in the JSON is240/720; this document's280/720 is a deliberately labeled manual
review alternative below293/742, not a changed catalog or altered calculator.

If supplemental-cost risk C is credible, review a much smaller **75/200** pair
instead; it affords1/3 five-minute one-output jobs, or3/9 initial clips at three
outputs/job, with ~62.6%/60.9% modeled margins. These amounts also remain
conditional. Prefer filling evidence gaps to selling unattractive low allowances
based on costs the business may not incur. **No currently certified safe pair.**

The 3,700/9,500 proposal still fails the B100,B500,B1000 scenarios across all
quoted outputs/edits. Attractive packages may become supportable at materially
higher verified utilization or with separately approved processing restrictions;
that is not demonstrated by a single short Whisper benchmark. A five-minute
one-output-only product would have a different binding workload from today's
three-output/one-edit rules. Smaller source caps, output/edit allowances or a
well-managed queue are proposals requiring approval, never assumptions silently
substituted into the current catalog.

Fee sensitivities0/3/5/10% plus the fixed USD0.05 are recorded in the JSON; even
the0% row retains that fixed-fee scenario. Higher fees or weaker PKR reduce the
allowance; the script accepts explicit fee/fixed/FX parameters for replay. The
60% test is applied to each package and full-credit workload, not an optimistic
mix of short jobs or breakage. Tax/refund/overage/labor uncertainty can consume
the remaining40%; they must be resolved before certification.

## Why these differ from191/486 and61/155

The previous files are retained as evidence, not rewritten:

| Change | Justification / effect |
|---|---|
| Deepgram allowance | Already zero in previous Whisper calculator; **no new saving claimed**. Legacy runtime admission still expects a DG rate component, which can over-reserve without calling DG. |
| CPU price plus full VPS | Replace USD0.00002/CPU-second **plus**13.20/100 with a single workload-weighted hosting pool. Corrects potential overlapping allocation, conditional on a real inclusive invoice. |
| Local storage/transfer price | Not automatically incremental cash; included only conditionally. Keep extra billed backup/egress separately in C. Contract evidence remains missing. |
|3x across all components | Replace opaque stack with explicit single25% or50% risk assumptions. No evidence proves either multiplier; sensitivity, not discovery of actual failure rates. |
| Gemini full chunks/output | B forecasts serialized synthetic payload and512 outputs; C uses32 full2048 outputs and serialization bound. Original USD0.007584 five-minute reservation is not actual usage. No model/rate change. |
| JSON protocol envelope | C corrects the old illustrative2048 fixed overhead for transcript re-escaping; do not call the old example a proven maximum. Runtime exact-byte admission is untouched. |
| Paid edit | Include one additional render/revision when prepaid. Old evaluator checked no edits, understating some resource entitlements. |
| FX300 vs277.0572 | Dated public offer raises reference USD revenue by~8.3%; no claim it is the actual billing-card FX rate. |
| Result | Prior planning191/486 -> conditional293/742; prior envelope61/155 -> conditional81/205. Both old and new are scenario ceilings, **none certified**. |

Expected blended contribution margin remains unknown. The first correction is
classification and transparency, not a claim that USD0.3545 was an actual bill
that can now be halved. The cost of a real job is unchanged by changing credits.
Shared-source transcription/analysis must not be charged once per initial output;
rendering and retained revised files must not be counted once per source only.

## Decisions and certification evidence

Before activating either package the owner must choose the *cost basis and
operating envelope*, then approve exact price/version/credits—not merely pick
the largest modeled allowance. Specifically:

1. Confirm actual invoice amount/currency/tax/period, attributable host share,
   included transfer/storage and overage/backup rates; identify shared workloads.
2. Approve a dated FX/spread/tax assumption and actual merchant variable/fixed fees
   or an explicitly conservative fee scenario. No merchant onboarding investigation
   was performed. Merchant approval remains pending.
3. Supply local phase measurements, source/output/language mix, failed-job rate,
   retention and actual downloaded bytes; confirm supported duration and concurrency.
   Decide whether bounded downloads/failure abuse limits are required. Any policy
   changes need separate authorization and implementation before a hard cap claim.
4. Confirm the intended Gemini model/account rate and, under separate paid-test
   approval, collect usage receipts. No paid call is authorized by this audit.
5. Review280/720 (conditional B100),75/200 (conditional C), or another explicitly
   recomputed pair once evidence supports it. Higher-utilization alternatives
   require observed demand/capacity; no lower pair has owner approval yet.

Separate proposals: source-duration/output/edit-specific quoting, queue admission
and reservations that cover local Whisper CPU, contract-backed bandwidth policy,
retention choices and versioned credit rescaling. No automatic fallback, prompt/
model/limits change or silent wallet conversion. Quotes/rate policy must be
separately reviewed if revised. Actual deployment would still require the existing
fresh recoverable backup/versioning/rollback procedure; this audit does not deploy.

## Reproduction and verification

From backend root with the reviewed environment:

```powershell
.venv/Scripts/python.exe -m scripts.unit_economics_audit
.venv/Scripts/python.exe -m pytest tests/test_unit_economics_audit.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check scripts/unit_economics_audit.py tests/test_unit_economics_audit.py
.venv/Scripts/python.exe -m ruff format --check scripts/unit_economics_audit.py tests/test_unit_economics_audit.py
```

Save stdout as UTF-8 JSON if comparing the evidence artifact (PowerShell5 native
redirection defaults to UTF-16). Audit script reads only repository inputs and
prints JSON; there are no imports of deployment controllers or environment reads.
Financial math is Decimal, quotes use the real engine; float timestamps are only
synthetic transcript timing, not financial values. No database/Redis/model/provider
fixture or expensive benchmark/full-suite rerun is needed for this read-only change.
Tests exercise absent-evidence non-certification, old arithmetic reconciliation,
ceilings/ceiling+1, prepaid edits, FX/fees/volume sensitivities, Pro value and side
effect prohibition. Current audit test results are recorded in implementation status.
