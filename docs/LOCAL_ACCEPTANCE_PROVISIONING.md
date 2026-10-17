# Approved local acceptance provisioning — 2026-10-13

Approval authority: user explicitly authorized the existing
[approval sheet](ONE_SHOT_APPROVAL_SHEET.md), retaining the prohibition on
provider requests, AI enablement and breaker opening. That sheet is preserved
unchanged and SHA-256 pinned by the local command.

## Applied and verified

- Implemented `scripts/provision_acceptance.py` and local-only primitives in
  `src/zoclip/ops/local_bootstrap.py`; no HTTP bootstrap endpoint or auth bypass.
- Executed `--phase bootstrap`: separate account registered/verified/logged in
  through existing CSRF/auth/development-mailbox routes. Promoted under the
  SystemLimits/User locks with one immutable `ops.local_admin_bootstrap` event
  (NULL application actor, manifest-linked external operator). Existing sessions
  revoked atomically; fresh admin login/logout verified. Customer remains customer.
- Credentials, approval manifest and audit receipt are under ignored
  `var/live-ai-readiness/acceptance-admin/`, Windows current-user/SYSTEM only.
  No credentials are printed or accepted on the command line. Persisted email,
  payments, trials and AI settings unchanged. Manifest must be retained with
  future audit backups; no off-server backup is claimed here.
- Executed `--phase plan-credit`: exact approved free-plan version and one
  ADMIN_ADJUST +1 through authenticated admin routes, with existing CSRF, reasons
  and reviewed idempotency keys. No payment evidence or automatic trial grant.
- Read-only postconditions: one customer/one admin; one bootstrap audit;
  one plan price; wallet available=1/reserved=0; exactly one ADMIN_ADJUST ledger
  row (+1 available, 0 reserved); zero active authenticated sessions.
- Migration head remains `7b37ea061d28`. Zero jobs/outbox/provider requests/spend
  attempts/provider usage. Zero cost rates/policies. Breaker=true, policy absent;
  AI_ENABLED=false, DEEPGRAM_VERSION unset. PostgreSQL reachable, Redis PING passed.
  Source/private data and existing audit history were preserved; no reset/delete.

## Validation

Final `scripts/verify_acceptance_offline.py`: **53 passed**, 33.42 seconds,
including 11 new bootstrap/financial checks and the previous 42 cases.
Fresh mock PostgreSQL schemas were forward-migrated and preserved, never reset
or dropped. External sockets/DNS blocked, real provider keys excluded; fake
version strings were used only in mock schemas. Evidence:
`var/acceptance-guard-tests-46001f56bd1c45cba0ed2bfcf88b86a0/results.xml`.

New checks cover target isolation, reviewed-manifest binding, missing provider
evidence, exact numeric payloads, transactional rollback, concurrent bootstrap,
replay/audit identity, session revocation, customer/breaker protection, admin RBAC,
CSRF, credit idempotency/payload mismatch and the five-rate closed policy routes.
Initial failed test attempts were corrected; they are not counted as passes.
Windows asyncio's internal socketpair is allowed only inside its synchronous
implementation on its own thread; other non-readiness connections remain blocked.
Ruff passes; mypy passes for 74 application/provisioner/verifier files. Existing
Starlette/Authlib HTTPX deprecation warnings persist. No build/browser launched.

## Remaining actual blockers

1. Account-specific provider access/rate evidence remains absent. Gemini project
   access/quota for gemini-2.5-flash-lite needs console/support confirmation.
   Deepgram needs verified nova-3 English **batch** access and a concrete version
   valid for model=nova-3; no version may be invented or borrowed from a streaming
   example. Confirm the reviewed provider prices apply to the actual accounts.
2. The approval sheet explicitly prohibits creating the Deepgram rate before
   version verification. Therefore none of the five rates or the all-five-rate
   USD 0.05 policy has been installed. This is an evidence dependency, not a new
   request to approve the reviewed numeric values. No provider metadata request
   was made. The rates/policy phase is implemented and tested, but not executed.
3. Breaker opening and the live run remain expressly unauthorized. Persisted AI
   stays false; any future authorized run uses only the existing process-local
   opt-in and strict private approval attestation.

## Commands and evidence needed next

Already executed successfully from `D:\ZoClip-Project\backend`:

```powershell
.venv/Scripts/python.exe scripts/verify_acceptance_offline.py
.venv/Scripts/python.exe scripts/provision_acceptance.py --phase bootstrap
.venv/Scripts/python.exe scripts/provision_acceptance.py --phase plan-credit
```

After console/support verification, record only nonsecret facts privately in
`var/live-ai-readiness/acceptance-admin/provider-evidence.json`:

```text
account_rates_confirmed: boolean true (reviewed 0.0043/min, 0.0000001/input
  token and 0.0000004/output token apply to these accounts)
nova3_english_batch_confirmed: boolean true
deepgram_version: the exact verified string, never an example/alias
source: dated console/support evidence reference, no credentials
verified_at: actual verification date/time
```

Set only DEEPGRAM_VERSION to that verified value after review; leave AI disabled.
The already authorized installation command is then:

```powershell
.venv/Scripts/python.exe scripts/provision_acceptance.py --phase rates-policy
```

It refuses missing/inconsistent evidence before rate writes, logs in the existing
private admin, creates the five exact reviewed versions through admin endpoints,
binds their actual returned UUIDs, and installs only breaker=true policy
`acceptance-v1-policy-closed`. It has no breaker-opening mode. An uncertain
response requires inspection under the same keys; never invent replacement keys
or edit ledger/audit history. Further account checks are manual; no request to
Gemini/Deepgram is authorized by this document.
