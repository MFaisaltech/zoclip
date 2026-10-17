# Private staging deployment and rollback

For Phase8 Milestone6 use the [coordinated Vercel/SSH deployment runbook](PHASE8_PRIVATE_STAGING_RUNBOOK.md)
and its two-file private profile. It supersedes this base profile's split-origin
admin routing for the private browser dashboard only; all RBAC/CSRF remains.

Phase 7 prepares the existing modular monolith for Contabo Cloud VPS 4, Ubuntu
24.04, 4 vCPU, 8 GB RAM, 100 GB SSD, Germany. **No VPS deployment or production
launch is authorized.** All commands below are operator instructions for a later,
explicitly approved session. They have not been executed on Contabo.

The [2026-10-12 private staging preparation](PRIVATE_STAGING_PLAN.md) records the
supplied VPS address, outstanding inputs, existing Caddy/SSLH conflict checks and
sequenced operator commands. It does not authorize server access or deployment.

## Decisions and missing inputs

The supplied authorization overrides the blueprint's eventual public 80/443
listener: this Compose publishes **only 127.0.0.1:8443 and :8444**. Administration,
docs and payment webhooks are blocked at the customer listener. Admin routes
require the existing application session/RBAC/CSRF in addition to a private tunnel.
API, database, Redis and workers have no published ports. Only proxy joins an
ingress bridge for loopback host forwarding; API/DB/cache networks remain internal.
No frontend is deployed.
The edge subnet defaults to 172.30.70.0/24; check host/VPN routes and set
EDGE_SUBNET and PROXY_ADDRESS together if it conflicts. Only that proxy IP is
trusted for overwritten forwarded headers.

Required before any server work: VPS IP, approved non-root sudo SSH username,
independently verified SSH host-key fingerprint, key location (never its contents),
approved operator source CIDR/VPN, exact API/frontend domains and DNS ownership,
approved DNS certificate challenge method, backup destination/host fingerprint,
off-server age recovery identity custodian, backup maintenance window, alert
recipient/channel, recovery objectives and approved storage/retention policies.
Do not send passwords, private keys or live provider credentials in chat.
Email delivery is disabled; signup cannot finish email verification in staging.
Google remains disabled; enabling it later requires an approved HTTPS callback
`https://API_DOMAIN/api/v1/auth/google/callback`, exact verified app registration
and its existing readiness gate. Consult generated OpenAPI for the actual route.
Live AI/payment verification and representative render QA/capacity remain blockers.

## Host preparation (manual, approval required)

Install official Docker Engine and Compose plugin using the current official
Ubuntu instructions, plus Python 3, OpenSSH and a DNS challenge certificate tool.
Review package/security updates and record installed versions. Verify system time,
100 GB usable filesystem layout, memory/swap policy, Docker data-root capacity,
host firewall and Contabo network rules. Never put customer data in a public web
directory. Docker access is equivalent to root; do not grant it to app users.

After the SSH key works in a **second** session, validate an sshd drop-in with
`sudo sshd -t` before reloading SSH. Set `PermitRootLogin no`,
`PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
`PubkeyAuthentication yes`, and `AllowUsers APPROVED_SSH_USER`.
Keep the original session and Contabo rescue access until the second login passes.
For private staging allow SSH only from the approved operator CIDR, default-deny
inbound, and open neither 80 nor 443. Review IPv6 rules too. Example placeholders
must be replaced; never run a firewall rule with an invented source address:

```sh
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from APPROVED_OPERATOR_CIDR to any port 22 proto tcp
sudo ufw enable
sudo ufw status verbose
sudo ss -lntup
```

Docker-published ports can bypass UFW. Loopback binding, private Docker networks,
the Contabo firewall and an independent external IPv4/IPv6 port scan are mandatory;
UFW alone is not evidence of isolation. No Docker socket is mounted in services.

## Files, images and secrets

Place a reviewed checkout at `/opt/zoclip`. Build the app and ops images from that
checkout, scan packages/images with an approved scanner, record SBOM/package
versions and image digests. Python dependencies use `uv.lock --frozen`; base/uv/DB/
Redis/Nginx images are digest pinned. OS packages resolve security updates at build
time; record the resulting image digest rather than assuming reproducible apt.
Do not use mutable development tags for a server rollout.

```sh
cd /opt/zoclip
docker build -t zoclip-app:REVIEWED_COMMIT .
docker build -f deploy/Dockerfile.ops -t zoclip-ops:REVIEWED_COMMIT .
sudo install -d -m 0700 /etc/zoclip/private
sudo install -d -o 10001 -g 10001 -m 0700 /var/backups/zoclip
sudo install -m 0600 deploy/staging.env.example /etc/zoclip/staging.env
```

Edit metadata privately: APP_IMAGE/OPS_IMAGE must be reviewed immutable image
references, NGINX_IMAGE the reviewed digest, exact HTTPS origins and ALLOWED_HOSTS
JSON. Keep secrets out of metadata, shell history, process arguments and Docker
environment. Place these single files under PRIVATE_DIR:

| File | Contents / consumer |
|---|---|
| bootstrap_password | Independent high-entropy PostgreSQL bootstrap password; DB only |
| migrate_password, runtime_password | Independent high-entropy passwords; DB first initialization only |
| migrate_database_url | `postgresql+psycopg://zoclip_migrate:URL_ENCODED_PASSWORD@db:5432/zoclip`; migrator only |
| runtime_database_url | Same form, zoclip_runtime; API/workers only |
| backup_pgpass | `db:5432:*:zoclip_migrate:PASSWORD` with libpq escaping; backup only |
| backup_recipient | Approved public age recipient; no decryption key on application host |
| tls_certificate, tls_key | Valid DNS-challenge full chain and private key; proxy only |
| reporting_policy | `{"enabled":false}` until approved VPS invoice/FX/target assumptions exist |

Generate passwords using a local password manager or CSPRNG directly into files;
do not print them. For Ubuntu root-owned PRIVATE_DIR mode0700, individual mounted
files must be readable by their container UID: owner root with mode0444 inside
that inaccessible directory is the documented default. Use single-file mounts,
never mount PRIVATE_DIR itself. Host non-root access must be explicitly controlled.
Compose bind-backed secrets do not enforce the advertised uid/mode fields. Test
readability as UID999 (DB),10001 (app/backup) and101 (proxy), and test host denial.
The backup tool copies pgpass into a private0600 tmpfs file. Production Settings
loads `/run/secrets/database_url` as SecretStr; environment overrides still win,
so prohibit DATABASE_URL or provider keys in host/global Compose environment.
Rotating role passwords requires an approved SQL ALTER ROLE transaction and
matching file update/recreation; changing files does not rotate an existing DB.

Use DNS-01 for HTTPS without public ports. No ACME endpoint or DNS credentials are
included. Install the approved certificate files atomically, check nginx -t and
reload/recreate proxy. Renew before14days remaining and verify hostname, chain,
expiry and TLS1.2/1.3 through the private tunnel. Local tests use a two-day
self-signed fixture, never a production certificate.

## Reviewed rollout

First initialization creates separate bootstrap, schema-owner migrate and
non-owner runtime roles. Only a new empty volume runs postgres-init.sh. Never
reuse an older phase's volume or run this role setup blindly on an existing DB.
Existing installs need a reviewed role/ownership transition and verified backup.
Runtime cannot DDL/TRUNCATE, edit Alembic version or UPDATE/DELETE append-only
financial/audit tables. No financial trigger is disabled.

Prepare `/etc/zoclip/rollout-approved.json` privately after review:

```json
{"project":"zoclip-private","image":"REVIEWED_EXACT_IMAGE_REFERENCE","backup_verified":true,"schema_compatible":true}
```

For a genuinely new empty staging DB only, replace backup_verified with
`"new_empty_database":true`. The controller also checks that the public schema
has no tables before migrating; a populated schema cannot use this shortcut.
This marker records an operator review; it does not
grant authorization to this agent or prove a backup. Then, **after VPS approval**:

```sh
python3 deploy/manage.py plan --env-file /etc/zoclip/staging.env --project zoclip-private
python3 deploy/manage.py up --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml ps
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml exec -T api alembic current
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml exec -T api alembic check
```

The controller checks loopback-only publication, stops writers, starts DB/Redis,
runs the one-shot owner migrator, and waits for healthy workload. Failure leaves
writers stopped; investigate privately instead of repeating migration blindly.
Never use `down -v`, prune volumes, downgrade financial schemas or restore over
the active database. Migration7b37ea061d28 adds immutable erasure intents only;
populated downgrade refuses audit loss. Forward fixes are preferred.

From an approved workstation, after separate SSH authorization, forward8443/8444
to the server loopback. Resolve the real API hostname to local127.0.0.1 for TLS
verification. Preserve the real Host and Origin, use the production certificate
chain, and smoke `/health/live`, `/health/ready`, unauthenticated401, disallowed
host/origin, admin404 on customer port and authenticated RBAC on private admin
port. Do not bypass TLS validation. No public DNS change is necessary for the
private tunnel, but certificate DNS ownership is required.

## Resource and storage envelope

One API process (32 concurrent requests), one AI RQ process, one render RQ process,
one maintenance process. PostgreSQL max40 connections, each app process pool2/no
overflow; statement10s/lock5s/connect5s. Service memory ceilings: DB1.5GiB,
Redis256MiB, API768MiB, AI1GiB, render2GiB, maintenance256MiB, proxy128MiB.
Steady ceilings sum5.875GiB; leave roughly2GiB for kernel/Docker/cache. Migrator
512MiB and backup512MiB run with workload stopped. CPU quotas are ceilings whose
sum exceeds4vCPU; contention is possible, so measure tail latency and OOMs.
FFmpeg remains2threads with bounded children/deadlines and240s render default;
no user filter commands. Do not scale render above one. Raising AI to two requires
measured resource/spend evidence, revised quotas and explicit operational review.

Private retained materialized/reserved media pool40GiB; source4GiB/120min,
global pending10, ingestion2, per-user processing1. Reserve source+scratch+outputs
atomically in PostgreSQL; retain20GiB free at admission and alert below22GiB.
100GB decimal SSD is only about93GiB: provisional envelope system/images15GiB,
DB/logs8GiB, media40GiB, headroom20GiB, remainder~10GiB. Measure actuals; a full
local backup of40GiB media will not fit alongside that working set. The backup
tool refuses unless20GiB plus twice DB+media size is free. Reduce retained data
or provide an approved backup scratch destination before enabling unattended
backups; do not lower the headroom guard. No100-simultaneous-render claim is made.
The100-request health burst checks rejection, not video throughput. Representative
video sizes/durations, end-to-end queue latency, worker CPU/RSS, disk/I/O and
paid-provider-safe capacity tests are required on the actual VPS.

## Rollback and recovery

Record current/previous app digests, schema revision and verified backup manifest
before every rollout. For an image-only rollback whose previous code is reviewed
against the **current** schema, update approval.image to that previous digest,
set schema_compatible true and keep verified backup evidence:

```sh
python3 deploy/manage.py rollback --env-file /etc/zoclip/staging.env --project zoclip-private --previous-image PREVIOUS_IMAGE_AT_SHA256 --execute-local
```

Rollback never runs an old migrator or downgrades the DB. If schema/data are
incompatible, keep writers stopped and follow BACKUP_RECOVERY.md into separate
empty targets. Explicitly review post-backup financial events, uncertain provider
calls, privacy tombstones and external reconciliation before promoting a restore.
Never automatically replay UNKNOWN paid attempts or payment refunds.

Systemd templates under deploy/systemd are optional operator-reviewed units.
Boot uses `resume` to start existing containers, without recreation or migrations;
run the separately reviewed `up` rollout first. Do not edit metadata/images under
an existing running release without a new reviewed rollout.
They are not installed/enabled here. Backup intentionally leaves writers stopped
until verification/off-server transfer; do not enable the timer without an approved
maintenance/restart procedure and tested failure notification. See the backup and
monitoring guides for the remaining gates.

After reviewing unit contents and setting a tested alert hook, an approved
operator can install the boot/monitor units. These commands remain unexecuted:

```sh
sudo install -m 0644 deploy/systemd/zoclip-private.service deploy/systemd/zoclip-monitor.service deploy/systemd/zoclip-monitor.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/zoclip-private.service /etc/systemd/system/zoclip-monitor.service /etc/systemd/system/zoclip-monitor.timer
sudo systemctl daemon-reload
sudo systemctl enable zoclip-private.service
sudo systemctl enable --now zoclip-monitor.timer
```

Do not enable zoclip-backup.timer until its maintenance-window/restart and
off-server-copy procedure is staffed/approved and failure notification tested.

References reviewed: [Docker secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/),
[Nginx proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[Nginx request limits](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html).
