# Cost scenarios — 18 October 2026

Offline estimates, not invoices, approved account rates or a profitability promise.
The calculator now derives revenue from the unchanged canonical package prices,
including bonus credits. It no longer assumes PKR 20 per credit. Duration quotes
remain `max(60, minutes × 5 + requested outputs × 2)` for these no-edit scenarios.
A two-hour source costs 602/606 credits for one/three requested outputs. Starter's
500 credits cannot cover either quote; targets never override this check.

Assumptions: PKR 300/USD; Deepgram $0.0077/minute as an unverified conservative
allowance (not the account quote); Gemini $0.25/$1.50 per million input/output
tokens; compact text at 180 words/minute, eight UTF-8 bytes/word plus timed-group
metadata, 10% overlap, 16KB chunks, 2048 output tokens/chunk. Analysis maximum is
separately reported for all 32 permitted chunks. Runtime admission still measures
exact request bytes and conservative token/output maxima before paid calls.

Resource assumptions: 520 CPU seconds/output plus two seconds/source minute at
$0.00002/CPU-second; source 0.0333GB/minute retained seven days; two output GB-days
at $0.01/GB-day; 0.25GB/output downloaded three times at $0.02/GB. These are
planning resource allocations, not measured incremental invoices. Storage,
bandwidth and CPU may already be included in a server plan; avoid double counting
when replacing assumptions with contracted costs. Server allocation is $13.20 per
month divided by 100 completed jobs. Payment fees assume 5% plus $0.05 per PACKAGE
purchase, allocated pro rata to credits consumed. No merchant fee is asserted.
The separate risk scenario multiplies operating costs by three; it does not
authorize retries or change the isolated test's zero-paid-retry rule.

Illustrative Creator package allocation, USD. Contribution includes the assumed
fee and $0.132 server allocation, before the separate retry/risk reserve.

| Minutes | Outputs | Credits | Revenue | DG | Gemini | Compute | Storage | Egress | Fees | Contribution |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 60 | 0.1075 | 0.0077 | 0.0076 | 0.0104 | 0.0223 | 0.0150 | 0.0077 | -0.0952 |
| 1 | 3 | 60 | 0.1075 | 0.0077 | 0.0076 | 0.0312 | 0.0623 | 0.0450 | 0.0077 | -0.1860 |
| 5 | 1 | 60 | 0.1075 | 0.0385 | 0.0076 | 0.0106 | 0.0317 | 0.0150 | 0.0077 | -0.1355 |
| 5 | 3 | 60 | 0.1075 | 0.0385 | 0.0076 | 0.0314 | 0.0717 | 0.0450 | 0.0077 | -0.2263 |
| 30 | 1 | 152 | 0.2724 | 0.2310 | 0.0379 | 0.0116 | 0.0900 | 0.0150 | 0.0195 | -0.2646 |
| 30 | 3 | 156 | 0.2796 | 0.2310 | 0.0379 | 0.0324 | 0.1300 | 0.0450 | 0.0200 | -0.3487 |
| 120 | 1 | 602 | 1.0790 | 0.9240 | 0.1289 | 0.0152 | 0.3000 | 0.0150 | 0.0771 | -0.5133 |
| 120 | 3 | 606 | 1.0861 | 0.9240 | 0.1289 | 0.0360 | 0.3400 | 0.0450 | 0.0776 | -0.5974 |

All 24 package/duration/output scenarios fail the assumed 60% contribution target.
This does not establish measured cash losses: account pricing, CPU time, average
source/output size, retention, downloads, FX, provider retry incidence and actual
fixed/incremental hosting costs must replace these assumptions. Launch economics
remain BLOCKED. Prices, credits and cost controls were preserved.

Reproduce all Starter/Creator/Pro scenarios with:
`python scripts/release_economics.py deploy/economics.example.json`.
