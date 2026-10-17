# Original one-shot continuation — 2026-10-14

Implementation and offline verification only. No live authorization has been
created, consumed or activated. AI remains disabled; spending remains blocked.

The only supported original operation is
`bb187175-59ed-425f-8c7d-bae1ff83c4aa`, which stopped at
`resource_or_background_worker_gate` before uploads, jobs, reservations or provider
admission. This mechanism does not recover a provider call, consumed phase or
uncertain expense. It never deletes, renames, rewrites or resets an existing guard.

## Authorization and durable boundary

`scripts/continue_acceptance.py` defaults to a read-only file inspection. It prints
SHA-256 digests of the evidence and implementation, without creating an approval
or connecting to providers. Original coordinator, entry/result receipts and the
recovery receipt are pinned. All files hashed by the recovery receipt, including
the disabled dotenv and original source attestation, must remain unchanged.

Execution requires all of `--execute`, `--allow-paid` and a private fresh approval
file conforming to `ExecutionApproval`. The operator must obtain new explicit
execution authorization first; the prior implementation-only instruction is not
execution approval. The approval contains:

- The fixed original operation, a distinct authorization UUID, and the existing
  admin/customer UUIDs from the private bootstrap manifest.
- Operator, reason, timezone-aware approved/expiry timestamps (maximum two hours),
  and the freshly reviewed evidence/implementation SHA-256 digests.
- Strict boolean approvals for original execution once, audited spending-policy
  opening, and temporary process-local AI. All must be true for execution.
- Exact caps: one call per provider, one output, one existing credit, USD `0.05`.

No approval file is shipped or automatically generated. Do not set these approvals
until the owner explicitly authorizes the live continuation.

Under the existing PostgreSQL SystemLimits lock, consumption rechecks every
durable work/request/spend table, migration, verified account roles, the original
wallet/ledger, policy, all five rates and their immutable financial audits. It
rechecks time, historical hashes and the unchanged 512 MiB RAM/commit,
no-background-worker and media-disk gates after waiting for the lock. The CLI also
checks the exact sample, configured models/keys and idle Redis before consumption.

A fixed directory per original operation is an exclusive filesystem fence. An
empty directory or partial receipt is already consumed. A fsynced receipt is
written before one transaction appends the consumption audit and its full
SHA-256 hash audit to the existing immutable audit table. There is no migration
or new HTTP endpoint. Only a successful commit returns an in-memory secret permit;
only its hash is persisted. An exclusive workflow entry receipt prevents a second
start. Database audits also prevent replay from another filesystem path or with
another authorization UUID. A crash or uncertain commit does not permit a retry.

## Workflow and evidence preservation

The tracked continuation workflow uses the existing native executor, original
idempotency keys, provider dispatch guards, credit/budget checks and stop policy.
It records the original operation ID and writes exclusively under:

`var/live-ai-readiness/acceptance-admin/continuation-bb187175-59ed-425f-8c7d-bae1ff83c4aa/`

Original `live-run-entered.json`, `live-result.json`, coordinator, recovery evidence
and source attestation remain untouched. The new attestation is accepted by the
AI phase only after verifying the committed audit/hash, unchanged implementation,
authorization scope/expiry and workflow entry. `stopped.json` or `result.json`
blocks subsequent phases. Spending closure is attempted even if writing the stop
receipt fails. Existing provider/phase markers still independently prohibit retries.

Future execution, **only after separate explicit owner approval and private
approval creation**, from the backend directory:

```powershell
.venv/Scripts/python.exe scripts/continue_acceptance.py --execute --allow-paid --approval var/live-ai-readiness/acceptance-admin/<fresh-approval>.json
```

Do not rerun the historical coordinator. No reset or crash-recovery flag exists.
No unspent continuation allowance is transferable to a different sample, owner,
operation, model configuration or financial policy.

## Offline evidence

Combined focused gate: **126 passed**, 93.28 seconds; 56 continuation cases plus
the existing 70 provider/bootstrap guards. Includes real PostgreSQL concurrency,
distinct approvals/replay, partial files, failures before/after commit including
ambiguous acknowledgement, lost in-memory permit, tampering, resource failures,
strict/expired approval, unchanged controls and mocked workflow/provider failures.
Existing tests exercise actual native Deepgram/Gemini stages with mocked providers,
429/timeouts/crashes, committed provider slots and restart refusal.

All schema writes target new preserved schemas in the saved separate mock database.
No reset/drop/downgrade is used. Real provider keys are masked, external DNS/sockets
blocked. Evidence:
`var/acceptance-guard-tests-fa37672d38854e8080a5a131c1f55679/results.xml`.
Two existing HTTPX deprecation warnings remain. The initial restricted invocation
failed on Windows temporary-directory permissions; the successful run used the
required local access with the same offline network restrictions.

Focused Ruff lint/format checks pass; mypy passes for 77 application/driver files.
Historical hashes still match and the real continuation directory is absent.
No live authorization/audit consumption, AI enablement, spending opening, provider
request, deployment, commit or push occurred. Fresh explicit execution approval
is the remaining authorization blocker; runtime gates are checked at execution.
