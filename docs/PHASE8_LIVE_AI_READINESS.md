# Phase 8 live AI readiness — offline preparation

2026-10-13, Asia/Karachi. **Disabled preparation valid; live test BLOCKED.**
Continues Milestone 4 backend `4a238d3` / frontend `1618295`.
No paid/credentialed provider request, processing worker startup, deployment,
VPS operation, commit or push was performed. Fresh isolated local services and
forward migrations were subsequently prepared as recorded below. Public
documentation browsing is separate from provider API execution.

## Latest state — private keys, approved storage and local services prepared

The user saved both keys privately and confirmed ownership or the required rights
to send the supplied video's audio to Deepgram and transcript to Gemini after a
separate live-test approval. Both backend key fields are now nonempty; values
were never displayed/logged/copied into frontend configuration. Credential
authentication is still unverified because no provider requests are authorized.
`AI_ENABLED=false`; all three model/version fields remain empty pending selection.

The supplied path actually resolves to `test-media/sample.mp4.mp4` (double
extension): 121,865,257 bytes, 26.703160s, 2160x3840 H.264/AAC. It exceeds the
prepared 16 MiB source cap. Preserved it and created the separate local derivative
`D:\ZoClip-Project\test-media\sample-live-test.mp4`: **2,828,785 bytes**, **26.735042s**,
720x1280 H.264, mono AAC. Its SHA-256 is
`281841b42e88e04b3eaf4f361111550e4517e477c30f069e754bb5ee884bc3d0`.
This is input preparation, not an AI-generated deliverable. The new copy has
user/SYSTEM-only permissions. Source rights and identity are recorded privately
in `F:\ZoClip-LiveAI\source-attestation.json`, with live approval explicitly false.

The user selected **F:\ZoClip-LiveAI** for new private media, keeping the project
on D:. Created the previously absent directory with access limited to the current
Windows user and SYSTEM; `.env` MEDIA_ROOT now points at its `media` child.
Measured F: free is **91,726,725,120 bytes (~85.43 GiB)**, above the unchanged
22.078125 GiB conservative source/output admission requirement. No disk check was
bypassed, existing media moved/deleted, or headroom reduced. Available RAM was
3.187 GiB at inspection (snapshot, not a peak-memory benchmark).

Prepared **new** local services, independent of the existing PostgreSQL Windows
service. Used installed PostgreSQL 17 binaries read-only; all new database files,
logs and TEMP/TMP are under D: `var/live-ai-readiness/`. PostgreSQL binds only
127.0.0.1:55439; Redis binds only 127.0.0.1:56389 with generated private password,
64 MiB/noeviction cache limit. Private `.env` DB/Redis settings were updated while
preserving both provider keys, disabled AI and file ACL. No OS service installed.

Forward migrations reach **7b37ea061d28**. Authenticated PostgreSQL SELECT 1 and
Redis PING pass. The live-readiness database is `zoclip_live_readiness`, with zero
users/jobs/spend attempts/rates/policies and an **open circuit breaker**. Redis DB 0
is empty. No API, scheduler or processing worker started. These local services are
left running for preparation; nothing is deployed. Their private metadata is in:

```text
backend/var/live-ai-readiness/services-62f5c79dabb24c14a6d6fc1488390833/
```

`current-services.txt` points to that directory; `state.json` contains private
local service credentials and must never be printed/shared. The bundled MSYS Redis
requires `redis.conf` relative to its working directory; the initial absolute
Windows-path startup failed, then corrected startup/PING passed. Final metadata
records the actual running Redis PID. Existing services/data remain untouched.

Fresh full focused regression: **130 passed, zero failures/skips**, 134.87s:
`tests/test_config.py`, `tests/test_ai.py`, `tests/test_credits.py`. A newly created
separate `_test` database and Redis DB 15 were used; real provider keys were
excluded from the test process and external DNS/socket connections blocked.
This includes actual PostgreSQL overspend/concurrency/admission/unknown-cost and
mock AI pipeline regressions. Two existing Authlib/Starlette HTTPX deprecation
warnings remain. Evidence: ignored `var/live-ai-readiness/keys-configured-mock.xml`.
The live-readiness database and Redis DB 0 were not used for those fixtures.

### Model selection — manual account evidence still required

1. In [Google AI Studio](https://aistudio.google.com/), select the API project linked
   to this key and inspect its model selector **without sending a prompt**. Report
   whether stable `gemini-2.5-flash-lite` is offered. Do not choose a preview or
   `latest` alias. That is a conditional candidate for the existing adapter;
   its [model page](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite)
   currently limits 2.5 access to prior users. A visible selector is useful account
   evidence, not proof of key authentication or request compatibility.
2. If only newer Gemini models are offered, leave GEMINI_MODEL empty and report
   their names. The current adapter's zero thinking budget / legacy JSON-format
   request must be reviewed for that model and mock-verified before a live test;
   do not assume changing the env model alone is sufficient. No provider adapter
   migration was made in this readiness task.
3. For Deepgram, use `nova-3` as the documented English prerecorded candidate,
   `en`, no diarization/utterances, MIP opt-out true. Obtain an exact supported
   batch/en version from the account console/support. If the console does not
   expose a version, record that blocker; model-list metadata discovery needs
   separate authorization under the current no-provider-request instruction.
   Never use a [documentation example date](https://developers.deepgram.com/docs/version),
   `latest`, or `beta` as a supposedly verified pin.
4. Confirm the actual paid rate for those Deepgram options and Gemini standard
   text input/output rates. Keep Gemini keys restricted to its API; current
   [key guidance](https://ai.google.dev/gemini-api/docs/api-key) distinguishes auth
   keys from restricted standard keys and rejects unrestricted standard keys.
   Do not regenerate or reveal a key merely to inspect its restrictions.

Only after those selections are reviewed should the exact GEMINI_MODEL,
DEEPGRAM_MODEL and DEEPGRAM_VERSION values be saved. API key values are not needed
in chat. The USD 0.05 policy and all five rate versions remain **unapplied**;
no arbitrary CPU/storage prices or false model/version labels were inserted.
Conditional estimates and the prior command template below still apply, but
they do not authorize or fully specify a live run. Before paid approval we also
need an authorized test account/credits, reviewed local allocation rates, matching
policy IDs and a verified native worker/dispatcher launch path. Keep breaker open.

### Stopping only these new local services (optional, no data deletion)

From a terminal under the same Windows user, this stops the new Redis and
PostgreSQL targets after verifying their identity. It leaves all files/data intact:

```powershell
Set-Location D:\ZoClip-Project\backend
@'
import json, subprocess
from pathlib import Path
from sqlalchemy.engine import make_url
from urllib.parse import urlsplit
from redis import Redis
from zoclip.core.config import Settings
s = Settings()
assert not s.ai_enabled
pg = make_url(s.database_url.get_secret_value())
rd = urlsplit(s.redis_url.get_secret_value())
assert (pg.host, pg.port, pg.database) == ('127.0.0.1', 55439, 'zoclip_live_readiness')
assert (rd.hostname, rd.port) == ('127.0.0.1', 56389)
work = Path('var/live-ai-readiness/current-services.txt').read_text()
state = json.loads((Path(work) / 'state.json').read_text())
data = Path(state['postgres_data']).resolve()
assert data.is_relative_to(Path('var/live-ai-readiness').resolve())
with Redis.from_url(s.redis_url.get_secret_value(), socket_timeout=3) as client:
    client.shutdown(save=False)
subprocess.run([str(Path(state['postgres_bin']) / 'pg_ctl.exe'),
                '-D', str(data), '-m', 'fast', '-w', 'stop'], check=True)
'@ | .venv/Scripts/python.exe -
```

Do not stop the existing `postgresql-x64-17` Windows service. Redis is a disposable
transport cache; PostgreSQL remains authoritative. No stop command was executed
at this handoff. Restarting this private cluster requires its same data directory;
do not reinitialize it or run destructive migration downgrades.

## Earlier controlled-validation recheck — before key/service setup

The user reports obtaining keys and preparing the environment. Inspection of the
actual `D:\ZoClip-Project\backend\.env` still finds **both key slots empty**, all
three model/version fields empty, and AI_ENABLED=false. No process key overrides
exist. Its user/SYSTEM-only ACL and Git ignore still pass. No key values were
printed, changed, copied or logged; the frontend remains clean and has no provider
key variable references in the inspected non-generated files.

Configured PostgreSQL (loopback 55439) and Redis (loopback 56389) are unavailable:
read-only SELECT 1 / PING attempts fail with redacted connection errors. No
database mutation or service startup was attempted. Therefore actual migrations,
job isolation, spend history, rates and policy cannot be verified/configured yet.
Do not mistake a proposed JSON policy or offline Settings success for installed
PostgreSQL safeguards. The USD 0.05 ceiling remains **unapplied**.

Latest D: free is 23,245,893,632 bytes (about 21.65 GiB), still 460,312,576 bytes
(about 439 MiB) short of the conservative 16 MiB source/one-output requirement,
before any existing reservations. Available RAM improved to 1.46 GiB of 7.96 GiB;
this snapshot is not a workload benchmark. No capacity guard was bypassed.

No licensed 25–30 second spoken source/path/consent/hash has been supplied. The
repository's `tests/fixtures/source.mp4` is a synthetic 2.52-second tone/pattern
fixture and is unsuitable for the proposed live test. Source/license confirmation
and private key/model entry were requested; no substitute source was invented.

Fresh offline regression: **20 passed, 44 deselected**, 7.48s, two existing
HTTPX deprecation warnings. External sockets/DNS were blocked; TestClient's
internal loopback pipe was allowed. Provider adapters used existing MockTransport.
Evidence: ignored `var/live-ai-readiness/controlled-offline.xml`. PostgreSQL-backed
mock regressions were not rerun against the unavailable live-readiness services.

Public provider documentation was rechecked without credentialed discovery or
audio/text submission. Gemini 2.5 account restrictions and newer-model request
compatibility gates still apply. An exact supported Deepgram version must come
from account evidence; documentation example versions are not a valid selection.

### Maximum conditional reference estimate

For the prepared single 16,000-byte word chunk and one candidate, the existing
worker's conservative input-unit envelope is bounded by:

```text
empty Gemini body (1354 bytes)
  + 2 * (word JSON cap 16000 + prompt prefix 490 bytes)
  + worker allowance 1024
= 35358 input units
```

The factor two covers JSON escaping of the already serialized transcript. This
is a conservative byte-based admission bound, not a measured tokenizer result.
Output cap is 2048 tokens. Deepgram reserves one rounded-up minute for 25–30s.
Using the public standard/PAYG reference rates linked below, Decimal arithmetic
produces these **conditional single-success-path provider admission estimates**:

| Candidate | Deepgram | Gemini input + output | Total | Remaining under USD 0.05 for local allocations |
|---|---|---|---|---|
| Gemini 2.5 Flash-Lite | 0.0043000 | 0.0043550 | **0.0086550** | 0.0413450 |
| Gemini 3.5 Flash-Lite | 0.0043000 | 0.0157274 | **0.0200274** | 0.0299726 |

Sources: [Gemini standard pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Deepgram prerecorded PAYG pricing](https://deepgram.com/pricing).
Neither candidate is selected or account-verified; 3.5 request compatibility is
unverified. Actual Deepgram opt-out/options pricing is still needed. No free-tier
savings, tax assumptions, retries or made-up CPU/storage unit prices are included.
The total admission must also fit `520*render_rate + 1*storage_rate` and all existing
exposure under USD 0.05. Actual provider invoices are not guaranteed by this bound;
unexpected usage stays recorded and opens the breaker. Stop rather than raise it.

### Concrete policy values prepared, not applied

Per-job/user-daily/user-monthly/global-daily/global-monthly limits: decimal string
"0.05" each; one open reservation; five expense rows; output ceiling 2048;
render CPU envelope 520; storage envelope 1. The Gemini input rate must admit the
35358-unit conservative envelope. Source preflight's duration-based input
assumption must be reviewed separately (the schema's max 1000 units/second gives
at most 30000 units at 30 seconds); successful preflight does not reserve future
provider spend. Each actual call still checks the full conservative amount.
Breaker stays open until explicit approval. All five actual rate versions and
their IDs remain missing. No fake model labels/rate IDs or local unit prices were
installed merely to make policy validation pass.

### Exact existing test command template — NOT RUN

The existing provider smoke helper accepts an already admitted owned PROCESS job:

```powershell
# Only AFTER all blockers are resolved and explicit paid-test approval is recorded.
# $ownerId and $jobId must be the real UUIDs from the isolated account/API response.
# No API key belongs in a command argument or process log.
Set-Location D:\ZoClip-Project\backend
$env:AI_ENABLED = 'true'             # temporary process override, approval required
$env:ZOCLIP_ALLOW_PAID_SMOKE = '1'    # helper's separate explicit opt-in
try {
    .venv/Scripts/python.exe scripts/ai_live_smoke.py --owner $ownerId --job $jobId --allow-paid
} finally {
    Remove-Item Env:ZOCLIP_ALLOW_PAID_SMOKE -ErrorAction SilentlyContinue
    Remove-Item Env:AI_ENABLED -ErrorAction SilentlyContinue
}
```

This is a **template**, not a fully bound runnable test: source, owner/job UUIDs,
models/version, rates and services are missing. The file `.env` stays false;
temporary enablement after approval must be scoped to the reviewed worker process.
The helper can drive generation zero and then requires existing normal maintenance/
RQ dispatch for later generations. It verifies transcript/suggestions only; it
does not upload, approve clips, render or settle. Do not run it alongside a second
executor for the same job. Prefer one normal worker pipeline and UI observation
for the full end-to-end acceptance; use the helper as an alternative, not an
additional paid test. Native worker setup needs review: default worker/maintenance
entrypoints contain Linux `/tmp` paths; do not present them as verified native
Windows launch commands or run simulator/browser worker scripts for live work.

The full proposed acceptance remains: owned licensed upload -> actual quote and
explicit credit confirmation -> transcript/highlights -> one explicitly selected
classic-caption/center-framed MP4 -> private download -> exactly one SETTLE and
bounded usage evidence. It cannot run until the recorded blockers are cleared.
No live approval has been granted and no provider call has been made.

## Local preparation actually completed

There was no backend `.env`, DATABASE_URL or provider key configuration in the
inspected process. Created ignored `backend/.env`, restricted on Windows to the
current user's SID and SYSTEM, with inheritance disabled. No key was supplied,
invented or copied. `GEMINI_API_KEY` and `DEEPGRAM_API_KEY` are empty private slots;
model/version fields are deliberately empty. `.env.example` is unchanged.

The file keeps `AI_ENABLED=false`, payments/trials disabled, email disabled and
imports disallowed. It points at **unprovisioned** loopback preparation targets:
PostgreSQL port 55439 / database `zoclip_live_readiness`, Redis port 56389 / DB 0,
and a new `var/live-ai-readiness/media` path. These are reserved names, not claims
of functioning databases, credentials or services. No existing data was changed.

Test limits: source cap 16 MiB; output cap 16 MiB; one ingestion/pending job;
one analysis chunk of up to 16,000 serialized word bytes; one suggested candidate;
15–30 second clips; 2,048 output tokens; two provider admissions/minute; 120 second
provider timeout. Native FFmpeg/ffprobe paths resolve to existing D: binaries.
Normal storage headroom remains 20 GiB. No synthetic-capacity override is used.
One AI worker and one render worker are the proposed future maximum, not started.

`scripts/ai_readiness.py` reads Settings and real filesystem capacity only. It
never imports a worker, opens a database/provider connection, or enables AI.
It reports key presence as booleans and validation errors as field names only.
It refuses enabled AI. A zero exit code means valid **disabled preparation**;
its report always leaves live approval and external checks pending.

From a normal local terminal under your Windows account:

```powershell
Set-Location D:\ZoClip-Project\backend
git check-ignore .env
.venv/Scripts/python.exe scripts/ai_readiness.py
```

Do not print `.env`, dump Settings, put keys in shell arguments/history or paste
them into chat. The restricted automation account needs elevated local access to
read this user-private file; your own Windows account already has access.

## Provider and model review

Existing `src/zoclip/ai/providers.py` uses locked HTTPX REST, fixed HTTPS
destinations, TLS validation, no redirects, no environment proxies and no implicit
HTTP retries. Deepgram receives streamed mono 16 kHz WAV at `/v1/listen`, with
Token authorization; Gemini receives bounded transcript text at
`v1beta/models/<model>:generateContent`, with `x-goog-api-key`.
The application reads **GEMINI_API_KEY**, not GOOGLE_API_KEY. Keys remain backend
SecretStr settings; no frontend environment or code change was made.

- [Deepgram models/languages](https://developers.deepgram.com/docs/models-languages-overview)
  document `nova-3` for English prerecorded audio. Flux is a streaming model and
  is not the selection for this adapter. `DEEPGRAM_MODEL=nova-3` is a candidate,
  not an account-verified selection. [Version guidance](https://developers.deepgram.com/docs/version)
  requires obtaining an actual supported version; do not use `latest`/`beta` or
  treat documentation example dates as real Nova-3 versions. An operator can
  review the console/support or the [model-list API contract](https://developers.deepgram.com/reference/manage/models/list)
  to obtain a concrete batch/en version. No credentialed discovery was executed.
- Gemini's [2.5 Flash-Lite model page](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite)
  currently restricts 2.5 access to prior users; it recommends newer models for
  new projects. Therefore `gemini-2.5-flash-lite` is only a conditional candidate
  for an eligible account. Do not assume a new test project can access it.
- The existing Gemini request sends `thinkingBudget: 0`, `responseMimeType` and
  `responseJsonSchema`. The [REST reference](https://ai.google.dev/api/generate-content?hl=en)
  still documents those fields, with response-format deprecation guidance, and
  recommends thinkingLevel for Gemini 3+. Current [thinking guidance](https://ai.google.dev/gemini-api/docs/thinking)
  uses model-specific levels. A newer model is **not** a verified drop-in choice.
  Account access, exact body/schema compatibility and output usage parsing remain
  gates. No provider adapter migration was made during configuration preparation.

Published price references checked on this date, **not installed into a policy**:

| Candidate | Public standard/pay-as-you-go reference | Required qualification |
|---|---|---|
| Gemini 2.5 Flash-Lite | USD 0.10 input / 0.40 output per million text tokens | Prior-user access; exact request compatibility |
| Gemini 3.5 Flash-Lite | USD 0.30 input / 2.50 output per million tokens | Newer model compatibility unverified |
| Deepgram Nova-3 monolingual prerecorded | USD 0.0043/minute | Confirm this account's opt-out/options/contract rate |

Sources: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Deepgram pricing](https://deepgram.com/pricing). The Deepgram public table does
not establish a separate rate for this account's opt-out combination. Obtain a
written/console rate for the exact options; no assumed surcharge or discount.
Do not use free credits, batch rates, streaming rates or mock-fixture prices as
live paid rates. Gemini output accounting includes thinking/residual usage.

Keep `DEEPGRAM_LANGUAGE=en`, `AI_APPROVED_LANGUAGES=["en"]`, diarization and
utterances false, and MIP opt-out true. Deepgram's [data guidance](https://developers.deepgram.com/trust-security/your-data)
confirms the opt-out parameter; the fixed global endpoint does not promise EU
residency. Record consent for audio/transcript processing and the actual provider
terms. Do not submit a source requiring an unsupported regional endpoint.

## Real capacity

Measured D: free: **23,246,086,144 bytes = 21.650 GiB**. Local machine: 8 logical
CPUs, 7.96 GiB RAM total, **0.65 GiB available** at inspection. These are snapshots,
not throughput/RAM benchmarks or VPS measurements. No other process was stopped.

The actual storage admission in `media.service.capacity/source` requires:

```text
free >= 20 GiB headroom + existing unmaterialized reservations + 3*source_bytes + 2 GiB
```

A selected export additionally reserves `2*RENDER_MAX_BYTES`. For this private
16 MiB source / 16 MiB output configuration, a conservative combined minimum is
**23,706,206,208 bytes = 22.078125 GiB**, before existing reservations. Shortfall
at inspection: **460,120,064 bytes (~439 MiB)**. Even a near-zero source exceeds
the 22 GiB upload minimum. For the normal 4 GiB source / 256 MiB output defaults,
the combined minimum is 34.5 GiB, before existing reservations.

Provide sufficient real D: capacity with additional operational margin, or choose
an explicitly reviewed writable media volume. Do not delete existing data,
reduce headroom, use browser synthetic-capacity scripts or claim capacity from
file size alone. Database outstanding/retained reservations must be read before
admission; these were not queried because no isolated database exists yet.
Restore sufficient available RAM by closing applications you choose, then measure
actual peak memory during the small test. No measured speed is promised.

## Budget controls and proposed bounded test

**Proposed maximum application admission exposure: USD 0.05 total for one test.**
This is a ceiling awaiting approval, not a cost estimate, installed policy or
provider invoice guarantee. No live dollar amount has been authorized or spent.

The authoritative budget is PostgreSQL, not environment variables. All five
positive, versioned rates are required: Deepgram minutes, Gemini input/output
tokens, render CPU seconds and storage GB-days. The Deepgram rate model must equal
`deepgram_rate_label(settings)` (fingerprints model/version/language/all options);
both Gemini labels must exactly equal the chosen GEMINI_MODEL.

Before a future approved run, configure the isolated test policy with per-job,
user daily/monthly and global daily/monthly ceilings **all "0.05"**, maximum one
open reservation and five expense-attempt rows. The success path uses five rows:
Deepgram, Gemini input, Gemini output, render CPU, retention storage. This cap is
not five paid retries. Configure output ceiling 2048 and sufficient conservative
input units/rate bounds for the actual serialized request; review source-based
preflight separately from per-call admission. With the prepared render settings,
CPU admission requires at least `240*2+40=520` units and retention at the output
cap requires `ceil(16 MiB * 7 days / 1 GiB)=1` GB-day unit. These are accounting
envelopes, not measured CPU time, a storage invoice or invented unit prices.

Keep the circuit breaker open during setup. Only a reviewed audited configuration
may close it after approval. Admit each call in a committed transaction before
network I/O. Holds, UNKNOWNs, retries and sunk costs count in all limits. Missing
rates/budgets, mismatched labels and unresolved attempts fail closed. Actual usage
over an estimate is recorded and opens the breaker; remote charges cannot be
recalled by an application cap. Apply available provider project spend/usage
controls too, and verify what is a hard limit versus an alert. If reviewed worst
case plus local allocations cannot fit USD 0.05, **do not run** or raise the cap
without new explicit approval. Do not describe alerts as hard spending caps.

## Exact remaining manual actions and approval boundary

1. Create separate least-privilege test keys in the official Gemini/Deepgram
   consoles. Restrict the Gemini key to its API; use minimum transcription/project
   permissions for Deepgram. Enter only the key values in the existing empty
   backend `.env` slots using a private local editor. Keep AI_ENABLED=false.
2. Confirm an account-accessible Gemini model that accepts the current request,
   and a concrete Deepgram batch/en version. Record exact option-specific paid
   rates/terms privately. Fill GEMINI_MODEL, DEEPGRAM_MODEL and DEEPGRAM_VERSION
   only after review. If a newer Gemini model needs adapter changes, stop for
   compatibility work and mock tests first; do not probe it with unapproved calls.
3. Obtain real disk/RAM capacity. Provision a **new isolated** PostgreSQL database
   and Redis instance locally, with new private credentials, forward migrations
   and one authorized test account. Replace the unprovisioned loopback addresses
   in `.env`; never reuse the M4 simulator database or any existing user database.
   Review queued jobs and ensure the test database has none before enabling AI.
4. Prepare reviewed plan rules, audited test credits, five actual rate versions
   and the policy above through existing trusted backend operator contracts.
   Leave the breaker open and AI disabled. No financial configuration was applied
   by this readiness task; its existence/correctness remains unverified.
5. Record a licensed/self-recorded **25–30 second English video <=16 MiB**, clear
   speech and a coherent 15–30 second passage. Record its SHA-256, bytes, ffprobe
   duration/streams and consent in private test evidence. No suitable spoken
   source was supplied or selected. One output, zero edits, classic captions,
   center framing within existing quote features; no tracking/add-ons/reruns.
6. Rerun `scripts/ai_readiness.py`. Confirm both key booleans true, models/version
   present, binaries present, enough real disk and AI false. The script intentionally
   does not validate credentials remotely or certify model quality.
7. Present the source hash/duration, model/version/options, actual rate versions,
   exposure calculation fitting USD 0.05, isolated targets and run window for
   explicit approval. **Stop before enabling AI or starting real processing.**

Only after that approval: launch the normal API/maintenance and one real worker
per queue with matching isolated settings; obtain the actual quote and explicitly
confirm one PROCESS job. Observe real extraction/transcription/analysis, inspect
transcript/highlights, explicitly select one clip, render and download its private
MP4. Verify a single credit reserve/settle, bounded provider usage, audio/caption
alignment and no extra request on refresh. Record actual cost and stage timing.
Do not run the separate ai_live_smoke helper concurrently with RQ workers. Its
two opt-ins protect only that script, not ordinary workers.

Stop on auth/model/schema/quota/rate errors, uncertain outcome, unexpected spend,
capacity failure or poor quality. Existing 429 retry handling is bounded; inspect
and cancel rather than requesting more jobs. UNKNOWN expenses require evidence
before retry. Afterwards disable AI, stop only test processes, revoke temporary
keys and remove media through the normal lifecycle. Preserve financial history.

## Offline verification and limits

- Real disabled `.env`: Settings PASS; both keys/models absent as reported above;
  native binaries present; restricted ACL and Git ignore PASS. Validation was
  run with DNS and socket connections blocked, without printing settings/keys.
- Selected existing tests: **20 passed, 44 deselected**, 8.80s. Configuration,
  OpenAPI equality, mock HTTP authorization/no redirects, response bounds,
  chunking/alignment, fail-closed settings and usage/thinking accounting. External
  socket connections/DNS blocked; loopback allowed solely for Windows asyncio's
  internal TestClient pipe. HTTP adapters used existing MockTransport.
- New checker safety checks PASS: populated dummy-key redaction, enabled-AI
  refusal, malformed URL and Pydantic-error redaction, all sockets blocked.
- Ruff lint/format PASS for the new checker. No app/provider/endpoint/schema,
  dependency or migration changed. Full PostgreSQL/browser/render regression and
  real key validity/model compatibility/quality/speed were not rerun or inferred.
- Initial test harness failures were a too-strict socket guard blocking asyncio's
  internal loopback pipe and restricted pytest temp access; corrected final run
  passes. Two existing Authlib/Starlette HTTPX deprecation warnings remain.

Evidence is ignored under `var/live-ai-readiness/offline-final.xml`; `.env` is
ignored and private. Frontend is unchanged. This handoff is not permission to
enable AI, spend, deploy or publish changes.
