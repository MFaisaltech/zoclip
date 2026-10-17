# One-shot acceptance approval sheet — 2026-10-13

**Proposal only. Not permission to execute.** Supersedes the financial proposals
in [ONE_SHOT_ACCEPTANCE.md](ONE_SHOT_ACCEPTANCE.md); its sample, guard evidence
and execution commands remain applicable. No application code, credentials,
accounts, credits, prices, rates, policies or breaker state changed for this sheet.

## Decision and scope

Approve preparation separately from the live run. Target only development
PostgreSQL `127.0.0.1:55439/zoclip_live_readiness`, Redis
`127.0.0.1:56389/0`, and private media `F:/ZoClip-LiveAI/media`.
Persisted `AI_ENABLED=false` throughout. No general worker, scheduler, alternate
job, paid re-export, payment configuration change or production write is permitted.
Latest recorded state: verified customer exists; no admin, financial versions,
ledger entries or jobs; breaker open. Recheck these facts before provisioning.

## A. Local first-admin bootstrap proposal

There is **no existing first-admin provisioning command or public elevation
endpoint**. Financial endpoints correctly require an active verified admin.
The necessary trust boundary is an explicitly authorized local OS operator;
customer self-promotion cannot supply that authorization.

After approval, implement/review a one-purpose local bootstrap command, not an
HTTP endpoint. Reuse normal CSRF/register/verification/login workflows to create
one separate local account with random private credentials and the existing
development mailbox. Keep the acceptance customer a customer. Persisted email,
trials, payments and AI settings remain unchanged. Local mailbox verification
does not establish real email delivery.

The command must refuse unless the exact development DB/media target matches,
AI is disabled, breaker is open, no admin exists, and an operator approval
manifest identifies the exact newly registered verified active customer UUID
(different from the acceptance customer). Credentials/manifest get the existing
Windows user/SYSTEM-only ACL and remain ignored. No credentials in arguments/logs.

Use one PostgreSQL transaction: lock the SystemLimits singleton and selected
User row; recheck all preconditions; promote that user only; revoke that user's
existing sessions; append the existing immutable AuditLog; commit atomically.
Proposed event: `ops.local_admin_bootstrap`, actor_id=NULL (external OS operator,
not an impersonated application admin), target_id=new admin UUID,
request_id=approval operation UUID (36 characters). AuditLog has no reason or
metadata column: preserve operator identity, reason, UTC timestamp, exact target,
approval evidence and reviewed proposal hash in the private operator manifest
linked by that UUID; do not pretend those fields exist in AuditLog. Preserve
manifest evidence with the audit backup. Replay under the same singleton lock
may only report an already matching audit/role transition; ambiguity must abort.

Require a fresh normal admin login after promotion. All subsequent writes go
through existing admin RBAC, cookie/CSRF, reason and idempotency controls. Record
returned UUIDs/audit IDs privately. Propose a separately authorized audited
demotion/session revocation after acceptance; retain account and audit history.
This utility is still to be implemented and tested after approval, not available now.

## B. Exact test plan and credits

Use the existing enabled `free` plan's actual UUID, isolated DB only. POST
`/api/v1/admin/plans/{plan_id}/versions`, key `acceptance-v1-plan`, reason
`Isolated one-shot acceptance; no commercial pricing approval`:

```json
{
  "price_paisa": 0, "included_credits": 0, "valid_days": 0, "approved": false,
  "rules": {
    "credits_per_minute": 1, "credits_per_output": 0, "credits_per_edit": 0,
    "captions_credits": 0, "reframe_credits": 0,
    "max_source_seconds": 30, "max_outputs": 1, "max_edits": 0,
    "max_concurrent_jobs": 1, "daily_credits": 1, "monthly_credits": 1
  },
  "reason": "Isolated one-shot acceptance; no commercial pricing approval"
}
```

The existing free-plan fallback supplies these terms; no paid entitlement is
needed. After confirming available/reserved credits both zero and no prior
adjustment, POST `/api/v1/admin/users/{customer_id}/credit-adjustments`, key
`acceptance-v1-credit`, body
`{"amount":1,"reason":"One isolated 27-second acceptance job; one output only"}`.
This writes one audited ADMIN_ADJUST +1, not payment evidence or a trial GRANT.
Never repeat with a new key if the response is uncertain; inspect the ledger.

Quote: source_seconds=27, output_count=1, edit_count=0, captions=true,
reframe=true. Charge = ceil(27/60)*1 = **1 credit**. Successful delivery:
ADMIN_ADJUST +1 -> RESERVE 1 -> SETTLE 1 -> available=0/reserved=0.
Final failure releases credit but retains sunk/uncertain provider expense and
consumed dispatch markers; a released credit does not authorize a second test.
Credit has no proposed currency redemption value; PKR payment revenue is zero.

## C. Five proposed rate versions

POST each to `/api/v1/admin/cost-rates`, decimal strings for USD, reason
`Isolated acceptance rate reviewed 2026-10-13; assumptions as approval sheet`.
Keys are `acceptance-v1-rate-<component>`. Use returned real UUIDs only.

| component | model binding | unit | unit_usd | max_units | Envelope USD |
|---|---|---|---:|---:|---:|
| deepgram | `deepgram_rate_label(reviewed_settings)` | minute | "0.0043" | 1 | 0.0043000 |
| gemini_input | gemini-2.5-flash-lite | token | "0.0000001" | 36000 | 0.0036000 |
| gemini_output | gemini-2.5-flash-lite | token | "0.0000004" | 2048 | 0.0008192 |
| render | local-acceptance-cpu-assumption-v1 | cpu_second | "0.00001" | 520 | 0.0052000 |
| storage | local-acceptance-storage-assumption-v1 | gb_day | "0.001" | 1 | 0.0010000 |

Provider prices are the public standard PAYG references checked 2026-10-13:
[Gemini text input/output](https://ai.google.dev/gemini-api/docs/pricing),
[Deepgram prerecorded Nova-3 monolingual](https://deepgram.com/pricing).
Confirm account-specific rates before installation; no free-credit discount is
assumed. Gemini receives text, not audio; no grounding, caching or batch discount.

Render/storage numbers are **proposed test-only internal accounting assumptions**,
not measured hardware costs, vendor charges or commercial rates. Their approval
does not change payment settings. CPU envelope = 240-second deadline * 2 threads
+ 40 = 520. Storage unit `gb_day` uses GiB in implementation; 16 MiB maximum MP4
* 7 days = 0.109375 GiB-days, rounded up to 1. This is an accounting envelope,
not permission to delete existing data or a measurement of total source/scratch cost.

Deepgram binding is `deepgram:` + existing `money.fingerprint(dg_options(settings))`
(SHA-256 of canonical options), including the **verified** version, language=en,
diarize=false, utterances=false, mip_opt_out=true. Do not create its rate until
that version is verified. No UUID/hash/version has been invented here.

Envelope at all five rate ceilings: **USD 0.0149192**, including provider portion
USD 0.0087192 and local assumptions USD 0.0062. Initial 27-second quote estimate
uses 27000 input units and totals USD 0.0140192; Gemini dispatch recomputes a
serialized-body byte bound +1024, failing before dispatch if above 36000 units.
These are application accounting bounds, **not a provider invoice guarantee**.
Actual billing, account pricing, taxes/FX, other account traffic and uncertain
remote outcomes require separate reconciliation. Larger returned usage can open
the breaker after expense occurs; a budget cannot undo a provider charge.

## D. Exact budget policy and breaker recovery

POST `/api/v1/admin/limits/versions`, key `acceptance-v1-policy-closed`,
reason `Install isolated USD 0.05 acceptance limits with circuit breaker open`.
Explicitly include **breaker=true**; schema default is false. Limits:

```text
per_job_usd=user_daily_usd=user_monthly_usd="0.05"
global_daily_usd=global_monthly_usd="0.05"
max_open_reservations=1
rate_ids=[the five actual returned UUIDs, one per component above]
input_tokens_per_second=1000
max_output_tokens=2048
render_cpu_seconds_per_output=520
storage_gb_days_per_output=1
max_attempts_per_job=5
```

Five attempts means five expense dimensions (Deepgram, Gemini input/output,
render, storage), **two provider requests**, not five request permissions. Limits
apply to this isolated DB, not the provider account or unrelated traffic. USD
0.0350808 of the USD 0.05 cap remains above the proposed envelope.

Only after explicit financial/opening approval and external checks pass:

1. Authenticate the separate admin; obtain current CSRF token. Read
   `/admin/limits`, `/admin/usage-costs`, jobs and the ledger. Confirm exact saved
   versions/rate bindings; zero HELD/UNKNOWN spend, no overspend, no pending
   provider requests, no other active work or enabled/background worker. Recheck
   service readiness/migrations, resources, sample hash and customer credits.
   Keep changes serialized; if anything differs, stop. Current open state is
   unconfigured fail-closed, not proof of a spending incident.
2. POST a **new** policy version with identical reviewed limits and five UUIDs,
   breaker=false, key `acceptance-v1-policy-open`, reason
   `Approved isolated one-shot acceptance; preflight reconciled; open breaker`.
   Existing configure_policy locks SystemLimits, binds the new immutable policy,
   updates breaker and appends `costs.policy_created` atomically. Read back policy
   and audit event. Never directly UPDATE system_limits, erase expense records,
   zero unknown costs or reuse a changed payload under an existing key.
3. Opening the breaker alone does not enable AI. Keep persisted AI false. After
   completion/failure, propose closing through another audited policy version,
   breaker=true, key `acceptance-v1-policy-stop`, same limits, reason
   `Close isolated acceptance after completion or stop; preserve spend evidence`.
   Closing does not cancel an already dispatched remote request. Unexpected
   HELD/UNKNOWN or overrun blocks recovery until evidence is reconciled under
   separate authorization; no consumed phase may be rerun.

## E. External account evidence still required

- Gemini: privately identify the key's actual project in AI Studio/Cloud console,
  confirm API/key restrictions and gemini-2.5-flash-lite availability/quota for
  that project without submitting a prompt. The [official model page](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite)
  restricts 2.5 access to prior active users. A public listing/key presence is not
  account authorization; obtain support confirmation if the console is ambiguous.
  Do not silently substitute a model or upgrade billing.
- Deepgram: console/support must confirm nova-3, English, prerecorded/batch access
  and a concrete supported version string. [Version docs](https://developers.deepgram.com/docs/version)
  default omitted version to latest, but current adapter always sends version and
  application/one-shot guards require a nonempty fixed pin. Leave
  DEEPGRAM_VERSION unset until verified; no latest/beta or guessed dated version.
  [Model metadata](https://developers.deepgram.com/guides/fundamentals/model-metadata)
  documents GET /v1/models and GET /v1/projects/{project_id}/models: only with
  separate permission for provider metadata requests, select STT Nova-3/en with
  batch=true, and confirm the returned version is valid for model=nova-3 on
  /v1/listen. Documentation's streaming-only example is not a batch pin.
  No authenticated metadata request was made; console/support is the current path.
- Preserve only model/version/access/rate facts and evidence date, never API keys.

## F. Executor review and approved-run sequence

Reviewed acceptance_once.py, acceptance.py, paid_request and HTTPProviders.
Exclusive fsynced binding/phase files prevent re-entry; PostgreSQL job/wallet
locks, request history and committed consumed dispatch slots protect each provider
before I/O. One analysis chunk/candidate; two explicit checkpoint stages, no
retry loop. Deepgram must succeed before Gemini. HTTP transport has no automatic
retry/redirect; marked 429 stops instead of normal requeue. Timeout/crash/restart
cannot obtain another dispatch permission; existing receipts can reconcile only.
42 prior offline checks cover these paths; they were not rerun for this doc-only work.

Fresh validation: the plan, +1 adjustment, five rate shapes and both policy
shapes pass existing Pydantic schemas; credit calculation and all cost totals
pass Decimal assertions in memory. Deepgram used a schema-only label and policy
UUIDs were in-memory placeholders, never actual proposed bindings or persisted
IDs. No database or provider connection was needed; this does not validate
account access or installation. Historical low-memory limits still require a
fresh resource check before even a small render; no build/browser was launched.

Boundary: at most one dispatch each under the preserved isolated binding and
driver, not guaranteed remote exactly-once billing. It does not govern ordinary
unmarked jobs, other applications or an operator who resets guards. Never delete
markers/edit checkpoints, create replacement jobs, start a general worker or
restart a consumed phase. HTTP timeout is not an absolute total wall-clock or
invoice cap. Conservative false stops are acceptable.

After provisioning/financial approval, implementing/testing bootstrap, external
evidence and separate explicit live-test approval, use the commands in
[ONE_SHOT_ACCEPTANCE.md](ONE_SHOT_ACCEPTANCE.md#exact-commands-and-stop-conditions):
inspect/offline verifier -> authenticated sample upload -> validate once -> normal
1-credit quote/reservation -> bind exact PROCESS job -> AI phase once with
--allow-paid, temporary ZOCLIP_ALLOW_PAID_ACCEPTANCE=1 and private strict-boolean
attestation -> inspect real transcript/highlight -> approve one clip -> render
once -> authenticated private MP4 download -> ledger/expense/dispatch audit.
Only the approved executor creates an enabled in-process Settings object;
persisted AI_ENABLED remains false. Clear the temporary opt-in in finally.

Stop on any missing evidence/approval, wrong target/hash/version/rate, unexpected
history or active work, insufficient resources/credit/budget, 429/error/timeout,
ambiguous response, invalid transcript/highlight, crash or consumed marker. No
automatic retry, model fallback, new job or financial repair is authorized.

**Approval requested:** local bootstrap implementation/provisioning; this exact
isolated plan/+1 adjustment/five rates and closed policy; subsequent audited
breaker opening after checks. Live execution requires its own explicit approval
after the unresolved external account/version checks are satisfied.
