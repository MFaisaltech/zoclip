# Two-package pricing review — activation blocked

Whisper closeout: commit `24ce3a64e7c588e99508ab4587e5d99a46ee4447`,
[CI 39168348997](https://github.com/MFaisaltech/zoclip/actions/runs/39168348997)
succeeded: **641 passed, 81 skipped**, 226.29s, with Docker/container health and
asynchronous private ingestion smokes passed. No benchmark, image rebuild or
backend redeployment was repeated for this closeout. Current staging has seven
healthy services, default Whisper and explicit original Deepgram fallback.

## Owner proposal and decision gate

| Plan | PKR | Proposed credits | Conditional target |
|---|---:|---:|---:|
| Creator | 2000 | 3700 | 61 |
| Pro | 5000 | 9500 | 158 |

Targets use the actual quote engine: one output from a 300s source, no edits,
captions/reframe included, 60 credits per job. They are integer divisions, not
invented clip allowances; extra outputs, duration and edits require exact quotes.
The higher package is slightly cheaper per credit. Bonus credits 0; displayed
totals are the whole grant. Existing prepaid 30-day processing access remains;
no subscriptions or automatic renewals. Existing free trial is copied unchanged.
The proposal raises its monthly usage ceiling to the proposed purchased amount
so the old 2500-credit ceiling does not make most purchased credits unusable.

**Neither proposed allocation passed the existing 60% scenario margin target.**
Owner response: **review lower allocations before activation**. No lower numbers
have been approved. Original proposals remain unchanged in a separate draft.

## Conditional lower allocations for review

| Scenario | Creator ceiling | Pro ceiling | Creator/Pro five-minute, one-output targets |
|---|---:|---:|---:|
| Existing planning assumptions | 191 | 486 | 3 / 8 |
| Conservative admission envelope | 61 | 155 | 1 / 2 |

These are model-derived ceilings at 60% margin, **not verified sustainable offers**.
Pro has slightly better value per credit in both alternatives. They have not
replaced 3700/9500 or been installed. Merchant fees, FX, production usage/mix and
resource allocation remain unverified; neither alternative can be certified yet.

For each profile the evaluator checks every 1..120-minute duration and 1..3 outputs
against `credits.service.calculate()`. It finds the worst allocated cost/credit
and solves:

`max_credits = floor((price_USD * (1 - fee_fraction - target_margin) - fixed_fee) / worst_cost_per_credit)`.

Tests check the ceiling and ceiling+1 against that inequality. Unknown economics
never becomes approval even with optimistic volume assumptions.

## Costs and assumptions

Confirmed: local transcription removes a Deepgram API invoice from the default
path; the retained fallback is inactive. VPS benchmark cold CPU 39.010763s for
25.14725s audio is measured. Google's public Gemini 3.1 Flash-Lite text list rates
are USD 0.25 input/USD 1.50 output per million tokens, checked 2026-10-20 against
[official pricing](https://ai.google.dev/gemini-api/docs/pricing). Account-specific
rates and real full-pipeline token consumption are not verified.

The evaluator keeps the existing planning assumptions instead of lowering costs
to fit the desired credits: CPU USD 0.00002/s; render 520 CPU seconds/output;
storage USD 0.01/GB-day, source 7-day retention; 3 downloads/output at 0.25GB and
USD 0.02/GB; 3x operating-risk reserve; VPS USD13.20/month allocated over 100 jobs;
FX 300 PKR/USD; gateway 5% plus USD 0.05/purchase. These are assumptions/allocation
reserves, **not measured invoices**. CPU/storage/bandwidth allocations may overlap
the fixed VPS allocation, so do not interpret them as proven incremental cash
charges. No internal CostRate was changed to manufacture a positive margin.

Planning estimates, before purchase gateway fees, including the 3x operating reserve
and USD 0.132/job VPS allocation:

| Source | Outputs | Quote credits | Local CPU allocation | Gemini | Total USD |
|---|---:|---:|---:|---:|---:|
| 5min | 1 | 60 |0.009308|0.007584|0.354475|
| 5min | 3 | 60 |0.009308|0.007584|0.626875|
| 30min | 1 |152|0.055847|0.037920|0.763100|
| 30min | 3 |156|0.055847|0.037920|1.035500|
| 120min | 1 |602|0.223386|0.128928|2.179543|
| 120min | 3 |606|0.223386|0.128928|2.451943|

The conservative envelope additionally reserves the full 4GiB accepted source
retention and 32 allowed analysis chunks. Worst pro-rata margins for the proposed
3700/9500 credits are approximately **-566.16%/-583.56%** under planning and
**-1966.33%/-2021.57%** under that envelope. These are pessimistic scenario results,
not measured losses or expected customer averages. Expected blended contribution
cannot be certified without actual workload and cost evidence.

30/120-minute completion is also unverified and projected to exceed current
Whisper/RQ deadlines. Their quotes are supported by the accounting engine, not
a promise those jobs finish on this host. Limits remain unchanged.

## Concrete implementation, without activation

- `deploy/pricing-proposal-20261020.json`: exact two-paid-plan draft, Starter
  retirement, unchanged trial, no bonus, calculated conditional targets.
- `deploy/pricing-economics-20261020.json`: reproducible arithmetic and explicit
  evidence gaps; `activation_allowed=false`.
- `scripts/two_plan_economics.py`, `scripts/prepare_two_plan_proposal.py`:
  read-only audit/generation; never modify the active catalog or CostRates.
- `src/zoclip/ops/catalog.py`: fail closed on a proposal before any catalog,
  wallet, entitlement or audit mutation. Unknown release statuses also fail. A strict
  review-only field also prevents older deployed installers accepting paid terms.
- `tests/test_two_plan_proposal.py`: proposal gate, quote-derived targets, ceilings,
  preserved old orders/entitlements, exact fictional grants and duplicate callbacks.
- Frontend review module/generator/component and `/pricing/proposal` exist only
  behind `ZOCLIP_PRICING_PROPOSAL_PREVIEW=1`; default is 404. Exactly two paid cards,
  original failed proposal, both lower alternatives, assumptions and no purchase
  actions. The default pricing page and generated active catalog are unchanged.

Verification: 74 focused backend price/billing/trial regressions passed, followed
by 6 final proposal tests. 55 frontend unit tests passed; desktop/mobile and active
pricing browsers 3 passed/1 skipped with preview enabled, and route-closure 1
passed/1 skipped with it disabled. Skips cover the deliberately opposite flag
branch. Typecheck, focused lint, Ruff/mypy and production build with preview off
passed. No unrelated full suite or expensive model benchmark was repeated.

## Actual live state and required decision

**New pricing is not deployed.** Active catalog remains Free 0/60 dormant trial,
Starter 299/500, Creator 699/1300 and Pro 1299/2400, with paid terms unapproved and
payments/public AI disabled. Read-only staging verification found no CostRates,
no active cost policy, breaker on; customer wallets, ledger, reservations, orders,
entitlements, source/media records unchanged. Seven services are healthy; VPN API
and Vercel production/deployment protection remain. No paid calls or credit grants.

Choose the lower allocation pair and provide/approve defensible cost assumptions
before activation. Missing account-rate/payment-fee evidence remains a separate
gate; choosing a number alone does not prove profitability. Then the reviewed
catalog/frontend can be switched together after a fresh authenticated recoverable
backup, versioned data-preservation checks and rollback preparation. No migration,
new deployment or backup interruption was performed while this gate was closed.
Existing encrypted backups and the rollback release are preserved.
