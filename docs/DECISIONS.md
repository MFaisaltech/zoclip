# ZoClip decision register

Phase 0, 2026-10-09. Accepted here means design default, not implemented or tested.
No provider websites were consulted: no provider integration, current fee or model
availability claim is made. Verify official documentation in the implementing phase.

| ID | Decision/default | Rationale / revisit gate |
|---|---|---|
| D01 | Modular monolith, Python 3.12 and specified FastAPI/PostgreSQL/RQ stack | Fits single CPU VPS; dependency locks in Phase 1 |
| D02 | Sync sessions per request/task; short locked transactions | Clear financial consistency, no shared sessions |
| D03 | PostgreSQL outbox and job leases; Redis is delivery only | Recover DB/queue crash gap and duplicate workers |
| D04 | One AI and one render worker initially; two FFmpeg threads | Conservative 4-vCPU default; raise only with measurements |
| D05 | 120 min, 4 GiB, 20 GB headroom; atomic disk reservations | Limits coexist; capacity check may reject smaller files |
| D06 | Initial 40 GiB retained media, two ingestion slots, queue cap 10 | Provisional bounded working set, tune by benchmarks |
| D07 | PKR integer paisa, integer credits, fixed precision USD | Currency and credit quantities are distinct |
| D08 | Locked append-only wallet ledger and unique operations | Reserve once; settle successful deliverable or release once |
| D09 | Atomic spend holds include in-flight/unknown provider exposure | Prevent parallel calls overspending configured budgets |
| D10 | Paid work disabled without configured rates/models/budgets | No reliance on free quotas or guessed commercial economics |
| D11 | Prepaid packs/30-day entitlement; trial disabled | No assumed auto-recurring merchant support |
| D12 | Live payments disabled; mock only explicit dev/test | Merchant, current docs, verification and approval pending |
| D13 | Direct HTTPS allowlisted media only; compliant future adapters | No universal URL downloading; mandatory SSRF boundaries |
| D14 | Private local UUID storage; authenticated downloads initially | Owner isolation and revocation; object-store interface later |
| D15 | Host-only secure API cookie, same-site subdomains, explicit CORS/CSRF | Later v0 frontend consumes backend authority |
| D16 | 720x1280 H.264/AAC; selected intervals only; center fallback | CPU feasibility; actual caption/crop quality requires QA |
| D17 | Seven-day source/transcript/output TTL; 24h incomplete uploads | Provisional configurable policy; business/legal approval needed |
| D18 | Suggestions do not imply rendered completion or full-job settlement | Phase 4 is intermediate; hold timeout policy before public use |

## Pending decisions and operational risks

- Merchant provider, official verification/query/refund docs, onboarding approval,
  fees, settlement timing, late-payment policy and chargeback procedures. No live
  provider or recurring billing is promised. Implement disabled interface until verified.
- Approved PKR prices, credit conversion, output/edit quotas, spend ceilings,
  margin targets and USD/PKR reporting rate source. Need measured paid-provider,
  failed-job, compute, storage and gateway costs; no profitability claim.
- Domain, sender email, SMTP, Google configuration and callback URLs. Configure
  privately later; disabled capabilities must fail clearly, not fake success.
- Allowed direct-media hosts and permissions; other platform ingestion requires
  compliant adapter and product/legal review. Ownership attestation alone does not
  authorize bypassing provider protections.
- Published retention, financial/audit retention, backup destination and expiry,
  media disaster recovery, Terms/Privacy/subprocessor disclosures and takedowns.
- Exact codec/dimension/FPS bounds, scratch expansion estimates, output count caps,
  request deadlines, rate limits and max-per-job spend need fixture measurements.
- Full-job success criterion for automatic multi-clip requests and suggestions-only
  hold expiry must be explicit before billable public use; default is no partial charge.
- Remote API timeouts can mean billed-but-response-lost. Unknown attempts need
  reconciliation and retained spend exposure; do not claim exactly-once remote billing.
- Germany-hosted media and subprocessor transfers need clear customer disclosure;
  no compliance assertion before review. Urdu/English font shaping and multi-speaker
  reframe quality need representative QA.
- Shared 4 CPUs and small disk can bottleneck parser/extraction/render work; DB,
  images/logs and retained artifacts compete for the same SSD. Measurements and
  safe rejection matter more than theoretical concurrent user counts.

These are not blockers to Phase 1 scaffolding. They block affected integrations,
commercial launch or capacity claims at their respective gates.
