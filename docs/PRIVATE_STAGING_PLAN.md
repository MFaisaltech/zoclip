# Private staging deployment preparation — 2026-10-12

For the concrete approval packages,18443/18444 overrides, access-preserving
hardening and mandatory/deferred gates, use [PRIVATE_STAGING_PROPOSAL.md](PRIVATE_STAGING_PROPOSAL.md).

Preparation only, continuing Phase 7; this is not Phase 8 or deployment approval.
The user reports VPS preparation complete at `169.58.17.38`. No connection,
DNS lookup/change, registry access or external service operation was performed.
The host preparation claim has not been independently verified.

Update: the subsequently authorized [read-only VPS inventory](VPS_READONLY_INVENTORY.md)
verified the supplied SSH host-key fingerprint and observed host state. Caddy
already occupies8443; use the proposed loopback host ports18443/18444 only after
separate deployment approval. The original preparation findings below are historical;
no deployment or server configuration change was performed.

## Repository review

- HEAD: `c6814c2d7eec5cb44e76fe6b331e6a84ad52ed9f`; working tree initially clean.
- Read AGENTS.md, complete backend master spec, PROMPT 7, current status,
  DEPLOY_CONTABO.md, PHASE7_VERIFICATION.md, backup/monitoring guides and deployment
  code. Historical Phase 7 results remain historical; they were not rerun here.
- `deploy/compose.yaml` publishes only proxy `127.0.0.1:8443/8444`. DB, Redis,
  API and workers have no published ports. Customer ingress blocks admin, docs
  and webhooks; admin ingress still requires application authentication/RBAC.
- PostgreSQL 17 bootstrap/migrator/runtime roles, Redis 7.4 AOF/noeviction,
  one AI worker, one render worker, one maintenance process. AI, payment, email,
  Google, trial and URL imports remain disabled. No frontend is deployed.
- Migration head is `7b37ea061d28`; startup uses the schema-owner migrator,
  followed by runtime privilege revocations. Do not run migration as runtime.
- App/tools builds exist in the runbook, but server rollout requires an immutable
  app `@sha256:` reference. Decide an approved registry/artifact path first.
  Recorded local image digests do not prove those images are available on the VPS.
- Tools Dockerfile pins Debian package versions, including openssh-client. A
  fresh build may fail if those exact versions have left the package repository.
  No rebuild, version update or vulnerability assessment is claimed here.

Fresh local checks: Docker Compose **v5.5.1**, example metadata Compose validation
exit 0; all four `deploy/*.py` files parse; shell initialization file is LF in
Git and working tree. Resolved Compose assertions pass for loopback publication,
disabled AI/payment/email, two workers and internal data/queue/edge networks.
These checks do not start containers or validate secrets,
images, real TLS, host listeners, firewall rules or migrations on the VPS.

## Inputs still missing or unverified

Supply metadata/decisions only; enter passwords, keys and tokens privately.

| Area | Required input or evidence |
|---|---|
| Access | Approved non-root sudo SSH user, port (runbook assumes 22), private key **path**, independently verified host fingerprint/known_hosts file; operator IPv4/IPv6 CIDR or VPN; rescue access |
| Existing host | Ubuntu/version/architecture, CPU/RAM/swap/disk/inodes, Docker/Compose versions/data-root, time sync, UFW/Contabo IPv4/IPv6 rules, existing projects/volumes/routes and Caddy/SSLH listeners/forward targets |
| Release | Transfer method to `/opt/zoclip`, approved image registry or artifact delivery, exact app/tools/Nginx digest references, SBOM/scanner results, empty-volume evidence or existing DB transition/verified backup |
| Origins/TLS | Exact API hostname and HTTPS frontend origin (configuration only), DNS zone owner/provider, approved DNS-01 client/method, renewal owner/schedule and certificate paths |
| DNS | No new API/frontend A/AAAA records pointing to this VPS are needed for private tunnels. DNS-01 needs temporary `_acme-challenge.<API_HOST>` TXT, or approved CNAME/NS delegation; inspect existing CAA restrictions before issuance. No guessed domain/record values or public HTTP-01 |
| Secrets | Independent `bootstrap_password`, `migrate_password`, `runtime_password`; matching `migrate_database_url`, `runtime_database_url`, libpq-escaped `backup_pgpass`; public age `backup_recipient`; valid full-chain `tls_certificate`/matching `tls_key`; disabled `reporting_policy` |
| Backup | Destination host/account/private directory, verified destination SSH key, restricted transfer key/known_hosts paths; offline age identity custodian and recovery host; approved scratch capacity, encryption/config recovery, retention/deletion, maintenance/restart owner, schedule/timezone, RPO/RTO and restore cadence |
| Monitoring | Alert destination/channel and tested failure hook, retry/dedup owner; journal/disk/log limits; actual reboot and resource/capacity evidence |
| Test accounts | Approved verified staging user/admin provisioning procedure and private credentials, if authenticated smoke is required. Email is disabled, so signup cannot create a usable verified account; no existing admin or public bootstrap is assumed |
| Later gates | Live AI keys/models/versioned rates/budgets, merchant contract/credentials, email and Google registration, legal/subprocessor/retention approval, representative QA. These are deferred, not prerequisites to disabled-provider infrastructure startup |

No Redis password is required by this isolated-network profile. No session signing
or CSRF secret is consumed: implemented sessions/tokens are opaque and hashed in
PostgreSQL. Do not copy the blueprint's obsolete placeholder variables into service
environments. Keep Google/provider secrets absent and reporting disabled.

## Caddy/SSLH conflict review

The repository has no host Caddy/SSLH configuration, so actual conflicts are
**unknown**. A Caddy/SSLH listener on 80/443 alone does not collide with this
loopback-only Compose. Any listener on 8443/8444, including wildcard listeners,
can collide. An existing public Caddy route or SSLH forward to either staging
port could expose ZoClip even though Compose binds loopback. Inspect their active
service arguments/config paths and routes privately; do not print secret-bearing
configuration into chat. Check both host services and existing containers.

Do not stop, replace or reload Caddy/SSLH, install a second public proxy, or close
ports used by other applications under this plan. The original runbook's global
UFW/default-deny instructions must be reconciled with those existing services
before any firewall change. No new public ZoClip listener or route is authorized.
If 8443/8444 are occupied, select approved unused loopback ports in staging.env
and adjust tunnel commands; container ports stay 8443/8444. If 172.30.70.0/24
overlaps existing routes, set EDGE_SUBNET and PROXY_ADDRESS together before rollout.

## Operator commands — NOT EXECUTED, approval required

These commands implement DEPLOY_CONTABO.md rather than provisioning a new host.
Replace `APPROVED_*` metadata privately. Stop on any failed check. Shell blocks
are Bash on Ubuntu except the explicitly labeled workstation block. Do not run
them as one unattended script. External transfer/build/pull/issuance, host checks,
deployment and independent port scans each remain subject to explicit approval.

### 1. Approved SSH and host inventory

From an approved workstation (OpenSSH; substitute real paths/user):

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=APPROVED_VPS_KNOWN_HOSTS -i APPROVED_SSH_KEY APPROVED_SSH_USER@169.58.17.38
```

Use the independently verified fingerprint; ssh-keyscan alone is not verification.
Then read-only host inventory, preserving the existing services:

```sh
cat /etc/os-release
uname -m
nproc
free -h
swapon --show
df -h / /opt /var/lib/docker /var/backups
df -i / /var/lib/docker
timedatectl status
sudo docker version
sudo docker compose version
sudo docker info --format '{{.DockerRootDir}}'
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo docker volume ls
sudo docker network ls
ip -4 route
ip -6 route
sudo ss -lntup
sudo ufw status verbose
sudo systemctl status caddy sslh sslh-select sslh-fork --no-pager
sudo systemctl show caddy sslh sslh-select sslh-fork -p FragmentPath -p ExecStart
```

Missing optional services/directories may return nonzero; investigate rather than
claiming failure or success. Review the actual Caddy/SSLH route configs and host
Docker firewall/NAT rules locally. Confirm Contabo firewall independently through
the approved account. Do not allow 8443/8444 inbound; independent approved IPv4/
IPv6 scans must show no new reachable ZoClip ports. Existing services may remain
reachable; their presence is not ZoClip exposure evidence by itself.

### 2. Checkout, images, metadata and secrets

Transfer the reviewed tracked tree to `/opt/zoclip` using the approved method;
exclude `.env`, `.venv`, `.tools`, `var`, caches and local identities. Preserve any
existing installation. Verify the deployed source against commit `c6814c2` (for a
Git checkout: `git rev-parse HEAD` and `git status --short`). Do not reset an
existing dirty checkout or reuse another phase's DB volume.

After source/image acquisition approval, an operator with Docker privileges uses:

```sh
cd /opt/zoclip
sudo docker build -t zoclip-app:c6814c2 .
sudo docker build -f deploy/Dockerfile.ops -t zoclip-ops:c6814c2 .
```

Scan/review both resulting images and record SBOMs/digests. If registry use is
approved, authenticate privately and use this parameterized sequence (registry
location/permissions remain missing; these commands have not been executed):

```sh
RELEASE_REPOSITORY='APPROVED_REGISTRY/APPROVED_NAMESPACE'
sudo docker tag zoclip-app:c6814c2 "$RELEASE_REPOSITORY/zoclip-app:c6814c2"
sudo docker tag zoclip-ops:c6814c2 "$RELEASE_REPOSITORY/zoclip-ops:c6814c2"
sudo docker push "$RELEASE_REPOSITORY/zoclip-app:c6814c2"
sudo docker push "$RELEASE_REPOSITORY/zoclip-ops:c6814c2"
sudo docker image inspect --format '{{json .RepoDigests}}' "$RELEASE_REPOSITORY/zoclip-app:c6814c2"
sudo docker image inspect --format '{{json .RepoDigests}}' "$RELEASE_REPOSITORY/zoclip-ops:c6814c2"
```

Set APP_IMAGE/OPS_IMAGE to the exact corresponding repository digest references,
never mutable tags. Do not put passwords in arguments or an image ID into a guessed
repository `@sha256:` reference. Nginx's Phase 7 fixture
reference is `nginx@sha256:552e7481ca93ffccd046aa658dbbed22caefbc09c66fa7cd247cbb90b8a5c609`;
it still needs approved scan/platform/availability review for the VPS.

For the remaining host commands, use an approved root Bash session (`sudo -i`)
so protected metadata/files remain readable without granting app users Docker:

```sh
cd /opt/zoclip
umask 077
install -d -m 0700 /etc/zoclip/private
install -d -o 10001 -g 10001 -m 0700 /var/backups/zoclip
# First installation only; refuse to overwrite existing release metadata.
test ! -e /etc/zoclip/staging.env
install -m 0600 deploy/staging.env.example /etc/zoclip/staging.env
```

Edit `/etc/zoclip/staging.env` privately: exact reviewed immutable images,
PRIVATE_DIR/BACKUP_DIR, exact HTTPS origins, ALLOWED_HOSTS JSON and loopback ports.
Install all ten secret files from the runbook. Generate the three passwords with
a password manager/CSPRNG directly to files; do not print them. URLs and pgpass
must encode the same respective role passwords correctly. DNS-01 issuance/
renewal needs its separately approved client/provider commands; none are guessed.
Do not use the local fixture generator or self-signed fixture TLS on staging.

PRIVATE_DIR stays root:root 0700; single mounted files root:root 0444 permit
container UIDs while the parent prevents non-root host traversal. Test host denial
and mounted readability for DB UID999, app/tools UID10001 and proxy UID101 without
displaying contents. For example, with an approved available app digest:

```sh
APP_REF='APPROVED_APP_IMAGE_AT_SHA256'
test "${APP_REF#*@sha256:}" != "$APP_REF"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 --mount type=bind,src=/etc/zoclip/private/runtime_database_url,dst=/run/secrets/database_url,readonly --entrypoint /bin/sh "$APP_REF" -ec 'test -r /run/secrets/database_url && test -s /run/secrets/database_url'
```

Repeat with the exact consumer image/UID and each required mounted file. Validate
TLS hostname/chain/key pairing privately and >14 days validity. Leave the age
private identity off the VPS. `reporting_policy` contains `{"enabled":false}`.

### 3. Plan, first initialization and migrations

In the approved root Bash session, retain this function for the following blocks:

```sh
cd /opt/zoclip
dc() { docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml "$@"; }
dc config --quiet
python3 deploy/manage.py plan --env-file /etc/zoclip/staging.env --project zoclip-private
dc pull
docker volume ls --filter label=com.docker.compose.project=zoclip-private
```

Verify there is no existing populated staging DB/foreign volume. Do not delete
volumes to obtain an empty result. Prepare the protected approval marker, using
the **exact same** reviewed APP_IMAGE as staging.env:

```sh
test ! -e /etc/zoclip/rollout-approved.json
APP_REF="$APP_REF" python3 - <<'PY'
import json, os
from pathlib import Path
image = os.environ['APP_REF']  # Exact reviewed reference from the earlier block.
assert '@sha256:' in image
with Path('/etc/zoclip/rollout-approved.json').open('x') as target:
    json.dump({'project': 'zoclip-private', 'image': image,
               'new_empty_database': True}, target)
PY
chmod 0600 /etc/zoclip/rollout-approved.json
python3 deploy/manage.py up --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc ps --all
dc exec -T db pg_isready -U zoclip_bootstrap -d zoclip
dc exec -T db psql -v ON_ERROR_STOP=1 -U zoclip_bootstrap -d zoclip -c 'SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname IN ($$zoclip_bootstrap$$,$$zoclip_migrate$$,$$zoclip_runtime$$);'
dc exec -T db psql -v ON_ERROR_STOP=1 -U zoclip_bootstrap -d zoclip -c 'SELECT version_num FROM alembic_version;'
dc exec -T redis redis-cli PING
dc exec -T api alembic current
dc exec -T api alembic check
```

The controller stops writers, starts DB/Redis, verifies an empty public schema,
runs `deploy/migrate.py` packaged as `/app/scripts/migrate.py`, then starts and
waits for workload health. Empty-volume PostgreSQL initialization creates roles;
Redis initializes AOF transport storage itself, with no SQL seed or authoritative
ledger. Expected migration revision: `7b37ea061d28`. An ephemeral `run --rm`
migrator need not appear as a retained container in `ps`. Bootstrap is privileged;
runtime/migrate must not be superusers/role/database creators. Do not reseed
prices, grant credits or create test staff to make a failed health check pass.

Any rollout failure: keep writers stopped, inspect sanitized errors privately;
do not blindly repeat migrations. A failed first attempt after migration requires
the existing-DB backup/review path, not another new-empty assertion.

### 4. Private health and TLS checks

On the VPS:

```sh
dc exec -T worker-ai python -m zoclip.ops.health worker
dc exec -T worker-render python -m zoclip.ops.health worker
dc exec -T maintenance python -m zoclip.ops.health maintenance
dc exec -T maintenance python -m zoclip.ops.monitor
dc exec -T proxy nginx -t
dc port proxy 8443
dc port proxy 8444
sudo ss -lntup
python3 deploy/check.py --env-file /etc/zoclip/staging.env --project zoclip-private --backup-dir /var/backups/zoclip --certificate /etc/zoclip/private/tls_certificate
```

Expected proxy mappings: 127.0.0.1 only; seven steady services healthy. Worker
commands check the current worker's exact RQ identity and heartbeat; maintenance
checks its receipt. These are health checks, not successful paid/video jobs.
An initial host check should report `backup_missing_or_stale` before a real backup;
record this as an unresolved alert, never a pass. Missing cost policy deliberately
disables spending. No provider/merchant load or destructive outage drill here.

From an approved workstation, keep this tunnel open (local ports must be free):

```sh
ssh -N -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o UserKnownHostsFile=APPROVED_VPS_KNOWN_HOSTS -i APPROVED_SSH_KEY -L 127.0.0.1:18443:127.0.0.1:8443 -L 127.0.0.1:18444:127.0.0.1:8444 APPROVED_SSH_USER@169.58.17.38
```

In a workstation Bash shell with curl and trusted CA roots (Windows: use equivalent
`curl.exe` arguments), route the real hostname without public DNS changes:

```sh
API_HOST='APPROVED_API_HOSTNAME'
customer() { curl --noproxy '*' --connect-to "$API_HOST:443:127.0.0.1:18443" "$@"; }
admin() { curl --noproxy '*' --connect-to "$API_HOST:443:127.0.0.1:18444" "$@"; }
customer --fail-with-body "https://$API_HOST/health/live"
customer --fail-with-body "https://$API_HOST/health/ready"
customer -sS -o /dev/null -w '%{http_code}\n' "https://$API_HOST/api/v1/me"
customer -sS -o /dev/null -w '%{http_code}\n' "https://$API_HOST/api/v1/admin/audit-logs"
admin -sS -o /dev/null -w '%{http_code}\n' "https://$API_HOST/api/v1/admin/audit-logs"
customer -sS -o /dev/null -w '%{http_code}\n' -H 'Host: denied.invalid' "https://$API_HOST/api/v1/me"
customer -sS -o /dev/null -w '%{http_code}\n' -X OPTIONS -H 'Origin: https://denied.invalid' -H 'Access-Control-Request-Method: POST' "https://$API_HOST/api/v1/auth/login"
```

Expected: health 200; `/me` 401; customer admin 404; anonymous private admin 401;
invalid Host 400; disallowed-origin preflight 400. Do not use `-k`. Connect-to
preserves real Host/SNI and default HTTPS origin/port. Inspect TLS chain/name/
expiry and TLS1.2/1.3 support. Authenticated user403/admin200 and CSRF/cookie
smoke remain blocked until approved test accounts and private login are available;
keep session cookies out of command arguments/chat. Customer docs/webhooks must
also return404. Browser testing needs local DNS/hosts mapping and corresponding
origin/port review; curl health alone does not verify browser login.

### 5. Backup and rollback verification

Before allowing retained staging data, approve the backup capacity/destination/
identity/maintenance inputs. Worst-case 40GiB media plus working set cannot fit
a full local backup on 100GB. Preserve 20GiB headroom; use smaller retained data
or approved separate scratch storage, never lower the backup guard.

```sh
python3 deploy/manage.py backup --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
# Substitute the exact manifest basename printed by backup; no latest/wildcard.
MANIFEST='APPROVED_EXACT_BACKUP_MANIFEST.json'
dc run --rm --no-deps backup verify --manifest "$MANIFEST"
```

Writers remain stopped. Follow [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) for exact
strict-host-key scp/SSH transfer commands: two referenced ciphertext files first,
manifest last, remote SHA256 comparison. Retrieve from that off-server copy on
the approved isolated recovery host, restore to a **new empty** `_restore`/
`_restore_test` DB and media volume, and execute the tools image arguments
`restore --manifest "$MANIFEST"`. Destination/network/identity paths are missing,
so a runnable remote restore cannot yet be finalized. Record authenticated
decryption, DB head/drift, media inventory/hash, all-wallet ledger reconciliation,
privileges, privacy tombstones and measured recovery time before claiming backup
verification. Ciphertext checksums alone do not verify recoverability.

After approved verification/off-server receipt, first-release stop/resume rehearsal:

```sh
dc ps --all --quiet > /etc/zoclip/before-resume.ids
python3 deploy/manage.py resume --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc ps --all --quiet > /etc/zoclip/after-resume.ids
diff -u /etc/zoclip/before-resume.ids /etc/zoclip/after-resume.ids
dc exec -T api alembic current
dc exec -T api alembic check
```

Repeat all private health/monitor/TLS checks; verify outbox and balances. Container
IDs should be unchanged and no migrator run. This proves resume only if observed;
it is not previous-image rollback. No prior verified Phase 7 server release exists.
Until one exists, a failed first release stays stopped with data preserved:

```sh
python3 deploy/manage.py stop --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
```

For a later compatible-image rollback, record previous/current exact digests and
schema before rollout; obtain verified backup evidence and review previous code
against the current schema. Set staging.env APP_IMAGE **and** approval.image to
the previous exact digest; replace the marker with `backup_verified:true` and
`schema_compatible:true`, removing the new-empty shortcut. Then:

```sh
PREVIOUS_IMAGE='APPROVED_PREVIOUS_IMAGE_AT_SHA256'
python3 deploy/manage.py rollback --env-file /etc/zoclip/staging.env --project zoclip-private --previous-image "$PREVIOUS_IMAGE" --execute-local
dc images
dc exec -T api alembic current
```

Verify the actual API/worker image IDs match the recorded previous artifact,
schema revision is unchanged, migrations did not rerun, health/private ingress,
wallets/outbox and runtime privileges remain correct. Persisting APP_IMAGE matters:
`--previous-image` overrides only that controller process. Incompatible recovery
uses separate empty restore targets and explicit promotion review. Never downgrade,
`down -v`, prune volumes, overwrite active DB/media or replay uncertain paid IO.

Do not enable backup/monitor timers until notification and staffed restart/copy
procedures pass. Install optional boot/monitor units only through the existing
runbook after approval. Reboot verification needs its own approved maintenance
window and must also check existing Caddy/SSLH recovery.

## Next actionable steps

1. Confirm access metadata, exact origins/DNS-01 method, artifact path and backup/
   alert decisions above. Keep secret values private.
2. Explicitly authorize a read-only VPS inventory first; record Caddy/SSLH routes,
   firewall, port/subnet availability and volume state before approving changes.
3. Finalize immutable artifacts/TLS/secrets and the concrete rollout marker, then
   explicitly approve private deployment. Execute the reviewed commands and record
   actual results, including unresolved gates; no public release follows implicitly.

This preparation changes documentation only. No migration, application code,
dependency, deployed configuration, credentials or external state changed.
