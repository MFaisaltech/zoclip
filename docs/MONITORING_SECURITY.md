# Monitoring, privacy and staging security checklist

`zoclip.ops.monitor` emits sanitized aggregate JSON and exits1 on an alert. Run
inside **maintenance**, whose tmpfs contains its own last successful receipt:

```sh
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml exec -T maintenance python -m zoclip.ops.monitor
python3 deploy/check.py --env-file /etc/zoclip/staging.env --project zoclip-private --backup-dir /var/backups/zoclip --certificate /etc/zoclip/private/tls_certificate
```

Host checker covers Compose health,>=20 proxy429 responses/5min, missing/stale
backup (>26h), TLS expiry<14days and application monitor status. Application
monitor covers disk below22GiB, outbox>120s, dead worker>480s, maintenance>120s,
held/unknown exposure,>=80% configured daily/monthly spend,>=3 failed jobs/hour
with>=20% current-state failure ratio,>=3 recorded provider429 rejections/hour,
>=3 reversals/hour, any chargeback/hour and
modeled margin below target. State-based failure ratio is an operational hint,
not a historical SLI. Invalid/missing dependencies fail closed to an alert.
Spending-disabled is reported; an intentionally disabled staging policy is normal.
Alert hooks are local exit status/journal/systemd failure state only. An approved
OnFailure destination, delivery retry/dedup policy and end-to-end notification
test remain required before unattended staging; no email/Slack is sent here.

Nginx logs only status and duration; no URL/query/IP/auth/body/referrer. Uvicorn
access logs are off, app errors use sanitized classes/request IDs, PostgreSQL
statement logging is off, Docker json-file logs rotate10MiB*3 per service.
Restrict Docker/journal access, set a reviewed journal disk cap/retention on host,
and inspect fixture logs for accidental PII/secret leakage. Never enable SQL
parameter, provider-body or proxy request debug logging with real data.

`GET /api/v1/admin/operations` is audited server-RBAC and accepts UTC calendar
month start + exclusive end within the same month. It reports component+unit
provider minutes/tokens/CPU/storage units and actual estimated USD, failed job
reservation costs, all-period held/unknown exposure, gross/reversed/fee PKR paisa,
job states and disk/reserved/materialized storage. Optional private reporting
policy supplies decimal **strings** for version, monthly VPS USD, USD/PKR rate,
margin target and rate source. SHA256 records exact assumptions. Allocation is
prorated calendar time; net<=0 has null margin. Successful duplicate notifications
do not double count fees (conservative maximum per order); refunds use reversal
creation time. Prepaid edits share original reservations, invoice/tax/unrecorded
fees remain outside this estimate. No verified profit claim follows from it.
Default reporting policy is disabled; actual invoice/FX/target not invented.

## Retention and account deletion

Existing PostgreSQL-fenced cleanup continues: abandoned upload24h, retained source/
output7days maximum, intermediate suggestion hold24h, expired worker leases and
cancellation receipts. Capacity reservations release only after safe file cleanup;
active writers cannot be deleted. Maintenance adds bounded100-row expiry sweeps
per auth table/iteration. Credit expiry remains disabled.

Staff privacy CLI requires an existing server admin, target UUID and a reasoned
case, with explicit --execute; no public deletion/admin endpoint is added:

```sh
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml exec -T maintenance python -m zoclip.ops.privacy --actor ADMIN_UUID --user CUSTOMER_UUID --reason APPROVED_CASE_REFERENCE --execute
```

Review consent/legal holds/financial obligations privately first; reason must be
a minimal case reference, not PII. Record target UUID/case/time in an approved
access-controlled off-server privacy case registry before erasure, so recovery
can reapply requests newer than a restored daily backup. No automatic off-server
tombstone transport is configured. It atomically requests deletion of at most100
retained sources, rejects active writers/oversized batches, cancels jobs through
existing fences, disables access, pseudonymizes email, removes password/OIDC/token
data and revokes sessions. Replaying actor/reason is idempotent; changed intent
conflicts. Immutable erasure intent/audit and finance are retained. Media cleanup
is asynchronous and must be verified; provider-side retention/deletion and backup
expiry remain separate manual obligations. Disabled payment-risk accounts are
**not** automatically erased. Staff accounts require access resolution first.

## Operator acceptance checklist

- Confirm exact image/schema version, all service health, immutable secrets excluded
  from environment/history/context, correct mounted UID readability and host denial.
- Verify no public DB/Redis/API/worker/admin/docs/webhook ports on IPv4 **and** IPv6;
  perform external scan only after server authorization. Check Docker firewall rules.
- Verify secure cookie/CSRF, explicit origins/trusted hosts, one trusted proxy peer,
  TLS chain/renewal, login/rate limits and private media owner checks.
- Keep AI, trial credits, email/OIDC and payments disabled in this staging profile;
  production rejects mock payments. No browser redirect/manual paid switch grants.
- Preserve allowed-host SSRF importer/DNS/connected-IP/every-redirect verification;
  the AI worker's egress bridge never grants importer exceptions.
- Confirm one render + one AI process, bounded FFmpeg/pids/RSS/CPU/deadline, DB pool,
  queue limits,20GiB headroom and disk/inode/image/log growth monitoring.
- Check wallet reconciliation, outbox delay, failed/unknown costs and no duplicate
  charge/settle during crashes. Never zero exposure or blindly retry uncertain IO.
- Test disk-low, worker kill, DB/Redis outages,429/timeout/FFmpeg failure with isolated
  fixtures; verify honest job states/releases through existing regression tests.
- Verify encrypted backup/off-server retrieval/empty-target restore/privacy replay,
  then test actual alert delivery and runbooks with an approved operator.
- Complete live-provider, merchant, email/OAuth, legal/privacy notices, retention,
  representative quality/capacity and VPS gates before any launch approval.
