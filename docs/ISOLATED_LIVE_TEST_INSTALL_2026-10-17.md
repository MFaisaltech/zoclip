# Isolated operator installation - 2026-10-17

Subsequent update: the protected `staging-20261017-commercial1` release now includes
this existing migration and unchanged guarded code. Source consent and read-only
credential/model metadata checks were obtained; applicable account rates and full
isolated credential/account binding remain unverified. No spending approval was
recorded. See [current execution evidence](COMMERCIAL_DELIVERY_2026-10-17.md).
The installation details below describe the earlier installation and its original
image; they are retained as historical evidence.

**Installation succeeded on the existing private staging server. READY FOR
LIVE-TEST APPROVAL: NO**, pending isolated credential/account evidence below.
The owner's authorization covered installation and verification only. The test
remains PREPARED/unapproved; no paid provider call or live-test approval occurred.
This result supersedes the installation blocker in the preparation handoff.

## Installed state

| Item | Verified result |
|---|---|
| Migration | `8c42ab719e30` -> `c910a2e31f40` |
| Operator directory | `/opt/zoclip-private/isolated-live-test/20261017-cap-v1` |
| Reviewed code | Exactly four files, original SHA-256 manifest unchanged |
| Video | `9cced2b6-cf08-410c-b653-318eef1dc5fe` |
| Video SHA-256 | `4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80` |
| Source | 114,549,007 bytes; stored and probed 25,170 ms, rounded to 26 seconds |
| Isolated job | `6271dd2d-5d8e-4549-bc24-87c60cc68703` |
| Entitlement | PREPARED; approval hash/expiry and credential binding absent |
| Aggregate cap | USD **0.10**, durable PostgreSQL constraint and admission guards |
| Maximum requests | 1 Deepgram POST, 1 Gemini POST, 1 generated clip, **0 paid retries** |
| Dispatches / committed spend | **0 / USD 0** |
| Customer credits / financial processing | No grants, reservations, charges or normal processing jobs added |

Installed policy: Nova-3 English version `2025-07-31.0`, diarization/utterances
disabled, MIP opt-out enabled; Gemini `gemini-3.1-flash-lite`, one chunk/candidate,
36,000 conservative input units and 2,048 output tokens including thinking.
Permanent maximum-cost allocations are USD 0.004300 Deepgram, 0.012072 Gemini,
and 0.083628 local extraction/render/storage, totaling 0.100000. Local allocation
is an operator ceiling, not measured invoice usage.

## Fresh encrypted recovery point

Before migration, the existing staging workloads were quiesced using the existing
backup controller. PostgreSQL/media streamed directly into age encryption. The
exact returned manifest was used; no guessed/latest manifest was selected.

- Manifest: `20261017T102027-7be0d00e.json`
- Creation: 2026-10-17 15:20:33 Asia/Karachi (10:20:33 UTC).
- Manifest SHA-256: `6a149bf05fce5f784274762fb72d4f0c08c37ca804c9097c2e4cd58e9095b6b7`
- Both ciphertext hashes matched on-server and on the existing off-server backup destination.
- Local age decryption authenticated both streams through EOF; the database began
  with PGDMP and `pg_restore --list` accepted its archive inventory.
- Streaming media verification found two files and the exact selected-video hash.
- No plaintext backup/media was extracted to disk, existing database restored,
  recovery key uploaded, or prior backup removed.

This is authenticated backup/archive verification, not a new full restore drill.
The prior separate-target restore evidence is unchanged.

## Migration, data and safeguards

Upgrade creates only the two isolated tables, their constraints/indexes,
three trigger functions and five protective triggers. It revokes public-runtime
access to the new tables. It does not alter/drop existing business tables or
perform DML against existing customer/financial records. Alembic advances its
version; operator preparation appends one staff audit and creates the entitlement.

While workloads were stopped, every existing table was inventoried and its row
contents hashed before and after migration. All existing data matched, excluding
the intentional Alembic version change. After preparation, existing rows still
matched; the audit table retained all original rows and gained exactly one event.
No ordinary AI/payment/credit/source/job data changed. The source mount was read-only.

Staging verification confirmed:

- Exact source integrity and policy; decimal allocations sum to USD 0.10.
- All five database guards enabled; unique component slots and cap constraints valid.
- `zoclip_runtime` has no SELECT/INSERT/UPDATE/DELETE access to either new table.
- Five unsafe operations rejected in rolled-back savepoints: cap inflation,
  over-cap commitment, source-hash change, entitlement deletion, unapproved call insertion.
- Two independent concurrent application admissions both refused the unapproved job.
- Missing keys refused credential verification; no fake credential or account evidence installed.
- Fresh operator containers loaded the same entitlement, approval absence, zero calls
  and zero spend. Another cold inspection after the actual worker stop/start matched
  the complete preparation record and reverified all four installed file hashes.

No approval function or provider adapter was invoked. The new operator containers
used the existing immutable image, internal data network, no published ports,
read-only root/media, bounded resources and read-only mounted database secret.
Application images, services, environment values and network configuration were
not replaced. No public processing endpoint was added.

The same package's earlier local PostgreSQL/mocked-provider/FFmpeg regressions
remain **157 passed**; package hashes are unchanged. Those tests cover paid-call
failure/overrun, duplicate dispatch and child-process death. They were not rerun
against live data. Staging checks used the actual unapproved row and rollbacks;
no fictional approval or synthetic provider response was inserted on staging.

## Preserved access and operating state

All seven existing steady containers are healthy. The five workload containers
were restarted after backup; IDs, images, environment hashes, networks and port
bindings match their original snapshot. DB/Redis were not recreated or reset.

AI=false, breaker=true, payments=disabled, live payments=false, trial credits=false,
and public provider keys empty. WireGuard, reviewer firewall and VPN API socket
are active. The existing API listeners are the WireGuard-bound address and its
loopback-only TLS proxy; no wildcard/public listener was introduced.

Windows VPN requests with normal TLS validation: liveness/readiness 200, anonymous
identity 401, docs 404, expected frontend CORS. Public-IP ports 18443/18444/5432/6379
remain blocked. Signed-out custom and current generated frontend URLs both return
302 redirects to Vercel authentication. No Vercel setting/deployment was changed
and no protection bypass was used. This is HTTP/access verification, not a fresh
signed-in browser workflow test or an independent external IPv6 audit.

The deployment helper initially stopped before file upload/migration for a missing
import. Post-resume read-only checks were corrected to parse the existing
interface-qualified VPN address and allow its expected loopback proxy. The
reviewed four files were unchanged; no migration or security defect was found.

## Remaining blockers

The isolated operator has no securely supplied, verified provider credential
binding for this job. Public keys intentionally remain empty. Its configured
rate ceilings match the reviewed policy, but **applicable provider-account rates,
options and credential/model access have not been verified**. Public pricing or
local key presence cannot substitute for that evidence. No provider endpoint was
contacted during this installation.

Valid private account/credential/rate and source-processing-consent evidence must
be prepared for the exact source/job/policy. Approval is still a separate owner
decision; this installation authorization was not used as execution authorization.
No live-test spending approval is requested while those evidence gates remain open.

Retain the operator overlay and new migration for future schema-aware operations.
The running public image predates this additive revision; do not run its old
migrator against the new head or perform a schema downgrade. Normal service resume
uses existing containers without rerunning migrations. Future migrations/restores
must include the reviewed revision and its runtime-role revocations.

Sanitized receipts and private operational logs are under ignored
`var/isolated-live-test-20261017/install-session/`; matching server evidence is at
`/opt/zoclip-private/build-evidence/isolated-cap-20261017/`. Important receipts:
`backup.json`, `backup-authenticated.json`, `installation.json`,
`runtime-verification.json`, `access-verification.json`, `post-restart-inspection.json`.
