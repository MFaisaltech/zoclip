# Phase 7 private staging proposal — 2026-10-12

**Proposed only. No deployment or host changes approved or executed.**
Use this proposal with [PRIVATE_STAGING_PLAN.md](PRIVATE_STAGING_PLAN.md),
[VPS_READONLY_INVENTORY.md](VPS_READONLY_INVENTORY.md) and
[DEPLOY_CONTABO.md](DEPLOY_CONTABO.md). It supersedes the preparation plan's
host-port8443/8444 examples for this host. Application code, Compose and defaults
are unchanged. All command blocks below are future operator instructions.

## Proposed scope and approval boundaries

First deployment: one supervised infrastructure verification window on
`169.58.17.38`, project `zoclip-private`, source commit `c6814c2`.
Bind **127.0.0.1:18443** customer and **127.0.0.1:18444** admin; container ports
remain8443/8444. Recheck host listeners immediately before startup. Use the pinned
SSH key/fingerprint and SSH tunnels only; no public proxy route, API DNS address
record, frontend, public webhook or new inbound allow rule.

Preserve Caddy/SSLH/SSH/WARP/Privoxy/bgutil and other host services, their ports,
files, routes and Docker daemon configuration. Caddy already occupies8443;
SSLH forwards443 to it and22. Do not repurpose8000/8001. Keep AI/payment/email/
Google/trial/URL imports disabled, one AI worker and one render worker. No real
customer media, paid calls or customer credit grants during infrastructure smoke.

Separate approvals: artifact acquisition and secrets/TLS provisioning; targeted
firewall changes; private container rollout; backup/off-server restore; account/
SSH policy changes; any reboot or unattended operation. Approval of this proposal
must identify which work packages are authorized. No approval implicitly includes
DNS writes, public exposure or retirement of an existing access method.

## Decisions required from the owner

| Decision | Concrete proposal / missing value |
|---|---|
| Window/operator | Choose supervised deployment window, operator and rescue-console custodian. Confirm Contabo console login works and an independent session can reach the host |
| Access | Keep existing root key access during the first window. Choose approved non-root operator (`ubuntu` exists, access/sudo unverified) and independently test its key/sudo later; never grant app UID Docker access |
| Origins/TLS | Supply exact API hostname and HTTPS frontend origin; approve DNS zone/provider, DNS-01 client/challenge credentials storage and renewal owner. Do not reuse existing public-site TLS keys or Caddy routes implicitly |
| Artifact delivery | Choose approved private registry/repositories and authentication method. Build/scan app and ops, approve exact repository digests and SBOMs; deliver reviewed tracked checkout to `/opt/zoclip` |
| Backup | Supply destination SSH host/port/user/private directory, independently verified fingerprint, restricted transfer key/known_hosts paths, offline age recipient/custodian and separate recovery host |
| Recovery policy | Proposed nightly backup, seven daily/four weekly recovery points, monthly restore, RPO24h/RTO4h, staffed downtime/copy/resume. Approve or replace; these are targets, not measured results or enabled deletion |
| Backup capacity | Keep first window synthetic/near-empty. Approve smaller retained working set or separate backup scratch capacity before increasing media; preserve20GiB headroom and tool capacity refusal |
| Alerts | Choose an existing approved delivery channel/destination and on-call owner. Approve notifier integration, secret storage, delivery test and failure response; no outbound sender is implemented in the current templates |
| Network | Confirm Contabo IPv4/IPv6 boundary rules, approved source CIDRs, and whether narrow staging-only host guards below are desired. Observed source IP is not automatically an approved permanent CIDR |
| Authenticated smoke | Choose a documented, audited staging user/admin provisioning procedure. Email is disabled; do not bypass verification/RBAC or invent a public admin bootstrap |

Only metadata belongs in chat. Enter credential/key values through approved
private files or secret-management channels.

## Exact configuration and image requirements

First-install metadata at `/etc/zoclip/staging.env`, root-owned0600:

```dotenv
APP_IMAGE=APPROVED_APP_REPOSITORY@sha256:REVIEWED_MANIFEST_DIGEST
OPS_IMAGE=APPROVED_OPS_REPOSITORY@sha256:REVIEWED_MANIFEST_DIGEST
NGINX_IMAGE=nginx@sha256:552e7481ca93ffccd046aa658dbbed22caefbc09c66fa7cd247cbb90b8a5c609
PRIVATE_DIR=/etc/zoclip/private
BACKUP_DIR=/var/backups/zoclip
PUBLIC_APP_URL=https://APPROVED_FRONTEND_HOST
API_PUBLIC_URL=https://APPROVED_API_HOST
ALLOWED_HOSTS=["APPROVED_API_HOST"]
STAGING_HTTPS_PORT=18443
STAGING_ADMIN_PORT=18444
EDGE_SUBNET=172.30.70.0/24
PROXY_ADDRESS=172.30.70.10
```

Replace placeholders; review subnet/architecture/image scans before acceptance.
Do not put provider keys/DATABASE_URL/passwords in Compose environment or this
metadata file. Compose uses production settings with all integrations disabled.

| Artifact | Exact source reference / remaining evidence |
|---|---|
| App | Build Dockerfile from reviewed application commit; assign approved registry digest. Historical local verified manifest: `sha256:75c1f1ff371ce1ae835d93c40121cf2532d3ec2309f8ce25c85ccf1849fe3946`; availability/scan not established |
| Ops | Build deploy/Dockerfile.ops; assign approved registry digest. Historical local manifest: `sha256:51fa31a8866db6550e379c73c5a1efc5b03a88619e49bf8140475ac782e32405`; availability/scan not established. Pinned apt versions may require reviewed build maintenance |
| PostgreSQL | `postgres:17-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` |
| Redis | `redis:7.4-bookworm@sha256:4fa24486b8bcca8eec45ee0eb166edc674795e53a2b53d1a9ef263eecebaac85` |
| Nginx | Exact reference in metadata above, taken from Phase7 verification fixtures; requires approved platform/vulnerability review |

Historical image digests are evidence identifiers, not invented registry paths
or a claim that server images already exist. Fresh build digests may differ.

PRIVATE_DIR is root:root0700; single mounted files root:root0444, following the
existing runbook, with host traversal denied and consumer UID readability tested.
Ten required files:

| File | Required private contents / consumer |
|---|---|
| bootstrap_password | Independent generated high-entropy bootstrap password; DB UID999 |
| migrate_password | Independent migration-role password; DB first initialization |
| runtime_password | Independent runtime-role password; DB first initialization |
| migrate_database_url | psycopg PostgreSQL URL for zoclip_migrate at db:5432/zoclip, correctly URL-encoded password; migrator UID10001 |
| runtime_database_url | Matching URL for zoclip_runtime; API/workers/maintenance UID10001 |
| backup_pgpass | `db:5432:*:zoclip_migrate:` followed by matching libpq-escaped password; tools UID10001 |
| backup_recipient | Approved public age recipient; tools only, no decryption identity on VPS |
| tls_certificate | DNS-01 full certificate chain for exact API hostname; proxy UID101 |
| tls_key | Matching private TLS key; proxy UID101 |
| reporting_policy | `{"enabled":false}` until invoice/FX/margin policy is approved |

Generate directly to protected files, never stdout/history/arguments. No Redis,
session-signing or CSRF secret is required by this profile. No provider, SMTP,
Google or payment secret is needed for disabled integrations. DNS credentials
and backup transfer credentials need separate protected operator storage, never
application mounts. Essential nonsecret config and a private recovery/credential
rotation procedure must also survive loss of the VPS.

Alert configuration to finalize: destination/channel, delivery credential file,
operator escalation, timeout/retry ceiling, duplicate suppression and recovery
acknowledgement. Proposed starting policy for approval:10s delivery timeout,
three bounded attempts and10min duplicate suppression, with undelivered events
remaining visible locally. Send only service name, sanitized alert codes and UTC
time; never logs, environment, paths to media, tokens or provider payloads.
Once the chosen notifier and protected credential handling are implemented/tested,
the approved monitor/backup unit drop-ins can use
`OnFailure=zoclip-alert@%n.service`; that template does not currently exist.
No credential may appear in the unit command line or Docker environment. The
current checker treats any manifest older than26h and TLS under14days as alerts;
checksum/remote-restore evidence still needs the operator procedure.

## SSH and firewall hardening without removing current access

**SSH first window:** no sshd configuration edits/reload, root disable, password
disable, AllowUsers restriction or port changes. Confirm rescue console and a
second direct SSH session before any host work. Additive non-root key/sudo access
can be a later approved work package; preserve existing authorized_keys entries,
ownership and current sessions. Its verification is a fresh non-root SSH login,
`sudo -v`, and `sudo -n true` only if the chosen sudo policy permits it.

Key-only SSH is the intended eventual policy, but removing password/root access
requires explicit retirement approval after replacement access succeeds. For
that future change: archive current drop-ins privately, prepare a unique reviewed
drop-in, run `sshd -t` and context-specific `sshd -T -C user=...,host=...,addr=...`,
then reload (never restart) only after validation and a timed restore is armed.
Check root key, non-root key and existing SSLH access separately. No retirement
drop-in is supplied for immediate execution because existing access must remain.

Rollback pattern for a **new, uniquely named** future SSH drop-in only, after
review confirms all previous settings stay untouched:

```sh
# Proposed recovery script commands, not a current action.
if test -f /etc/ssh/sshd_config.d/00-zoclip-reviewed.conf; then
  test ! -e /root/00-zoclip-reviewed.conf.reverted
  mv /etc/ssh/sshd_config.d/00-zoclip-reviewed.conf /root/00-zoclip-reviewed.conf.reverted
fi
sshd -t && systemctl reload ssh
```

Prepare the protected rollback script before the change and arm it with
`systemd-run --unit=zoclip-ssh-revert --on-active=10m /bin/sh /root/zoclip-ssh-revert.sh`.
Cancel its timer only after fresh sessions pass. If locked out, use the tested
Contabo rescue console to run that script; keep the original session open.
If no safe replacement method/rescue access is proven, do not change SSH.
The validation flags follow the [OpenSSH daemon manual](https://man.openbsd.org/sshd).

**Firewall first window:** do not activate UFW/default-deny or rewrite the shared
host's rules. Optional narrow guards below affect only new staging ports and
preserve current22/443/8080/8443, WARP and other services. Host loopback binding
remains mandatory. The currently inactive UFW and permissive INPUT policy remain
an acknowledged host risk, not a production-hardening pass.

After explicit firewall approval, confirm eth0 is still the ingress interface,
both DOCKER-USER chains exist, and the two unique chain names below do **not**
exist in either family. Stop on any mismatch; never flush an existing chain.
Before applying, save the rule listing privately and prepare this rollback script
as `/root/zoclip-firewall-revert.sh` mode0700:

```sh
#!/bin/sh
set -eu
for tool in iptables ip6tables; do
  if "$tool" -w -C INPUT -j ZOCLIP-STAGE-IN 2>/dev/null; then
    "$tool" -w -D INPUT -j ZOCLIP-STAGE-IN
  fi
  if "$tool" -w -C DOCKER-USER -j ZOCLIP-STAGE-FWD 2>/dev/null; then
    "$tool" -w -D DOCKER-USER -j ZOCLIP-STAGE-FWD
  fi
  for chain in ZOCLIP-STAGE-IN ZOCLIP-STAGE-FWD; do
    if "$tool" -w -S "$chain" >/dev/null 2>&1; then
      "$tool" -w -F "$chain"
      "$tool" -w -X "$chain"
    fi
  done
done
```

Arm rollback **before** applying the following separately approved runtime rules:

```sh
set -eu
systemd-run --unit=zoclip-firewall-revert --on-active=10m /bin/sh /root/zoclip-firewall-revert.sh
for tool in iptables ip6tables; do
  "$tool" -w -N ZOCLIP-STAGE-IN
  "$tool" -w -A ZOCLIP-STAGE-IN -i eth0 -p tcp -m multiport --dports 18443,18444 -j DROP
  "$tool" -w -I INPUT 1 -j ZOCLIP-STAGE-IN
  "$tool" -w -N ZOCLIP-STAGE-FWD
  "$tool" -w -A ZOCLIP-STAGE-FWD -i eth0 -p tcp -m conntrack --ctdir ORIGINAL --ctorigdstport 18443 -j DROP
  "$tool" -w -A ZOCLIP-STAGE-FWD -i eth0 -p tcp -m conntrack --ctdir ORIGINAL --ctorigdstport 18444 -j DROP
  "$tool" -w -I DOCKER-USER 1 -j ZOCLIP-STAGE-FWD
done
```

These check both host INPUT and Docker-forwarded original destination ports;
UFW alone would not cover Docker publication. Verify a new direct SSH session,
existing SSLH access, existing service health and tunnel access, then inspect both
families' guard counters/rules. After approval of observed results, cancel only
the rollback timer with `systemctl stop zoclip-firewall-revert.timer`. On failure
allow automatic rollback or run `/bin/sh /root/zoclip-firewall-revert.sh` through
the still-open session/rescue console. Never restore a stale whole Docker ruleset.
Original-direction matching avoids dropping replies to container-initiated
connections solely because their remote destination uses a staging port; see the
[Netfilter conntrack options](https://ipset.netfilter.org/iptables-extensions.man.html).
The rollback scheduling pattern follows the [systemd-run timer documentation](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd-run.xml).
Verify the timer is actually armed and the protected recovery script is readable
before adding rules; a scheduling failure stops the change.

These are untested runtime-rule proposals; no persistence/reboot guarantee is
claimed. Persistence/interface coverage requires separate review before unattended
staging. Full source-CIDR/default-deny/Contabo hardening is a later host-specific
proposal requiring all service consumers and IPv6 paths to be identified first.

## Staged execution checklist and stop conditions

Use root Bash only in the subsequently approved server session. No block here
has been executed. No secret values are included. Do not paste all stages as one
script. Halt on a failed check and retain evidence privately.

1. **Access/preflight approval.** Reverify the pinned SSH fingerprint, rescue
   console and second login; record Caddy/SSLH/WARP/SSH baseline, resource/disk
   usage, firewall and active interfaces. Recheck staging ports/subnet:

   ```sh
   ss -lntup '( sport = :18443 or sport = :18444 )'
   ip -4 route
   ip -6 route
   systemctl is-active caddy sslh ssh warp-svc
   df -h / /var/lib/docker
   ```

   No18443/18444 listeners is the required result; a listener means stop. No
   overlap with172.30.70.0/24. No installs/restarts or release changes in preflight.

2. **Provisioning approval.** Follow the existing plan's checkout/build/push/
   secret-directory commands; approve scan/SBOM/immutable images before pulling.
   Create metadata with18443/18444, install mounted secrets privately and validate
   UID readability without outputting contents. Validate exact hostname/full
   chain/key pairing/expiry privately. No DNS-01 write without DNS approval.

3. **Rollout approval.** Optional staging-only guard work is separately approved.
   Check fresh volume state; create the runbook's exact-image new-empty approval
   marker only for a genuinely empty DB. Existing data requires verified backup
   and a revised marker. Then:

   ```sh
   cd /opt/zoclip
   dc() { docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml "$@"; }
   dc config --quiet
   python3 deploy/manage.py plan --env-file /etc/zoclip/staging.env --project zoclip-private
   python3 deploy/manage.py up --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
   dc ps --all
   dc exec -T db pg_isready -U zoclip_bootstrap -d zoclip
   dc exec -T redis redis-cli PING
   dc exec -T api alembic current
   dc exec -T api alembic check
   dc exec -T worker-ai python -m zoclip.ops.health worker
   dc exec -T worker-render python -m zoclip.ops.health worker
   dc exec -T maintenance python -m zoclip.ops.health maintenance
   dc exec -T proxy nginx -t
   dc port proxy 8443
   dc port proxy 8444
   ```

   Controller initializes empty PostgreSQL with separate bootstrap/migrate/runtime
   roles, starts Redis AOF, runs the owner migrator, applies runtime revocations
   and waits for workloads. Expected schema7b37ea061d28; proxy mapping must be
   exactly127.0.0.1:18443/18444. Seven steady services healthy; no other published
   ports. Verify actual image IDs/role privileges against the reviewed plan.

4. **Private acceptance.** Use the inventory's exact pinned Windows tunnel command
   forwarding local18443/18444 to server18443/18444. Use the preparation plan's
   curl `--connect-to` checks with real Host/SNI and trusted TLS; no `-k` or public
   DNS address changes. Health200, anonymous401, customer admin/docs/webhooks404,
   invalid Host400, invalid-origin preflight400. Authenticated RBAC/CSRF smoke
   waits for approved accounts. Repeat existing-service baseline and resource
   checks. Approve independent external IPv4/IPv6 scans for only staging ports;
   confirm no Caddy/SSLH path exposes staging. Host publication alone is not an
   independent external exposure test.

5. **Backup/alerts approval.** Before retained/customer data or unattended operation,
   execute encrypted quiesced backup, exact-manifest verification, off-server
   transfer/retrieval and isolated empty-target restore from BACKUP_RECOVERY.md.
   Check restored schema/media/wallets/privacy and record timing. Run:

   ```sh
   dc exec -T maintenance python -m zoclip.ops.monitor
   python3 deploy/check.py --env-file /etc/zoclip/staging.env --project zoclip-private --backup-dir /var/backups/zoclip --certificate /etc/zoclip/private/tls_certificate
   ```

   Missing backup alert on first boot remains an unresolved gate. First window
   can remain supervised with local checks; unattended operation requires a
   tested notifier. Implement an approved OnFailure unit/hook with target name
   supplied by the owner: current units have comments only, not alert delivery.
   No token in ExecStart/environment/chat, no outbound alert without approval.
   Verify synthetic failure reaches the chosen destination and recovery is
   acknowledged, then verify missing/stale backup, unhealthy worker, disk and
   TLS signals. Do not induce dependency outages on the shared host for this test.

6. **End of first window.** Stop ZoClip unless continued operation is separately
   approved. Leave volumes/files for review; do not enable boot/backup/monitor
   timers or reboot the shared host in this first rollout. Backup timer currently
   stops writers and has no automatic verified-copy/resume procedure.

## Rollback commands and evidence

First-release failure containment (retains all data and existing host services):

```sh
cd /opt/zoclip
python3 deploy/manage.py stop --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc ps --all
systemctl is-active caddy sslh ssh warp-svc
ss -lntup '( sport = :18443 or sport = :18444 )'
```

The staging ports should disappear, existing services should match baseline and
volumes remain. Do not run down-v/prune, downgrade schemas or overwrite DB/media.
Containment is the honest first-release fallback; no prior verified image exists.

After an approved consistent backup/verification/off-server receipt, stop/resume
rehearsal (define dc as above):

```sh
python3 deploy/manage.py backup --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
# Use exact emitted manifest basename and approved off-server copy/restore steps.
dc run --rm --no-deps backup verify --manifest APPROVED_EXACT_MANIFEST.json
dc ps --all --quiet > /etc/zoclip/before-resume.ids
python3 deploy/manage.py resume --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc ps --all --quiet > /etc/zoclip/after-resume.ids
diff -u /etc/zoclip/before-resume.ids /etc/zoclip/after-resume.ids
dc exec -T api alembic current
dc exec -T api alembic check
```

Same IDs/schema, no migration rerun, health/TLS/wallet/outbox checks must actually
pass. Never resume after failed backup/copy/verification merely to end downtime.

Later compatible-image rollback requires previous verified digest, current-schema
review and a verified backup. Persist previous APP_IMAGE in metadata and exact
approval.image with backup_verified/schema_compatible true, then:

```sh
python3 deploy/manage.py rollback --env-file /etc/zoclip/staging.env --project zoclip-private --previous-image APPROVED_PREVIOUS_REPOSITORY@sha256:REVIEWED_DIGEST --execute-local
dc images
dc exec -T api alembic current
```

Verify actual previous artifact IDs, unchanged schema and all private checks.
Incompatible recovery uses a separate empty-target restore and explicit promotion
approval, not financial-schema downgrade or blind provider/payment replay.

## Mandatory gates versus later production requirements

| Supervised private infrastructure window | Before retained data / unattended staging | Later public production |
|---|---|---|
| Explicit approval, trusted SSH, rescue and second session, free loopback ports, no public routes, valid TLS/exact origins, reviewed immutable images, secret mounts, empty-DB gate, migrations/health, existing-service preservation, local monitoring and stop fallback | Approved hardened access/network boundary, persistent protection review, off-server backup/retrieval/restore, retention and privacy process, tested alert delivery, staffed maintenance/resume, boot/reboot evidence and approved authenticated fixture QA | Live email/OIDC, approved merchant acceptance, real AI verification/rates/budgets, business/pricing/legal/subprocessor decisions, representative quality/capacity/economics, public DNS/proxy/webhook policy and separate launch approval |

An intentionally supervised infrastructure-only window does not waive any backup,
privacy or security requirement for customer data. It does not establish a usable
customer signup, AI processing, payment or public production service.

## Execution readiness

Ready as documented procedures: pinned SSH/tunnel access, availability recheck,
loopback Compose overrides, deployment controller, PostgreSQL/Redis initialization,
migration/worker checks, stop/resume fallback and existing encrypted-backup tools.
Execution still requires the appropriate approval and supplied inputs.

Not yet concrete/executable: real origin/TLS issuance, registry/artifact refs,
secret provisioning, backup destination/recovery paths, notifier/OnFailure unit,
non-root account changes and broad SSH/firewall hardening. Staging guard commands
are reviewable proposals, not tested firewall acceptance evidence.

This proposal changes documentation only. No VPS connection, operational external
service/account access, new migration, deployed configuration, container execution
or secret generation occurred during this proposal task. Official command
documentation was consulted online; this does not verify the proposed commands
on the VPS or its installed package versions.

Fresh local validation: resolved Compose with process-local18443/18444 overrides
publishes exactly the two loopback proxy ports and no others; proposal local
Markdown links/code fences/whitespace and `git diff --check` pass. No runtime,
firewall, migration, SSH-policy, notification or restore tests were executed.
