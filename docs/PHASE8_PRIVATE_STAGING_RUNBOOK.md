# Phase 8 Milestone 6 — private staging preparation

**2026-10-15 transport decision:** reviewers use WireGuard; SSH remains for
operations. Follow [the WireGuard access procedure](WIREGUARD_REVIEWER_ACCESS.md)
in place of this runbook's older reviewer tunnel/hosts-to-loopback instructions.
All Compose commands/publication guards remain loopback-only; a separate VPN-bound
host TCP proxy provides access. Map the API hostname to its VPN server address.

Prepared 2026-10-14. **No server, Vercel project, DNS, payment or provider action
has been executed. Every remote/mutating command below requires a separate
explicit deployment approval.** This does not authorize the paused AI acceptance
test. Its database, evidence, guards, receipts and approvals remain untouched.

Follow-up implementation: [resolved staging blockers and exact owner procedures](STAGING_BLOCKERS_RESOLVED.md)
adds audited single-use account invites, reviewer revocation and a browser private
access probe. This supersedes the original account-provisioning blocker below.
New head8c42ab719e30 requires the normal owner migration on future staging rollout;
acceptance DB is not migrated. Set STAGING_INVITE_EPOCH to a fresh deployment UUID.

## Chosen topology and release boundary

Owner selected same-site subdomains and SSH tunnel access initially. Use an owned
registrable domain, e.g. `app.staging.OWNED_DOMAIN` on Vercel and
`api.staging.OWNED_DOMAIN:8443` through each reviewer's SSH tunnel. Exact hostnames
are still missing. Do not deploy the reserved `example.invalid` local build.

Vercel serves the UI; the reviewer's browser calls the API directly with credentials.
Vercel servers cannot use the reviewer's tunnel. No Vercel rewrite, public API,
cookie proxy or third-party-cookie workaround is configured. The API listener is
published **only** on server `127.0.0.1:8443` (optional admin-only port8444).
The M6 proxy permits admin routes on8443 so the UI has one API origin; server
session/RBAC/CSRF checks still authorize every admin operation. The older base
profile's customer-port admin404 rule is intentionally replaced only in this profile.

Use BOTH Compose files for every M6 operation. Never fall back to the base profile
alone. Compose >=2.24.4 is required for the network `!override` tag. The private
profile removes AI-worker egress; all application/DB/Redis networks are internal.
No Gemini/Deepgram keys are mounted. AI, purchases, trials, Google login, external
media imports, public signup and email delivery stay disabled. `breaker=true`
means **spending blocked**. API/workers refuse startup otherwise, and private
staging admin API cannot write `breaker=false`. These checks never repair the DB.

Container supervision reuses restart-unless-stopped, health checks and systemd.
One API process, one AI RQ worker (also handles ingestion), one render RQ worker
and one maintenance scheduler. Service RAM ceilings total5.875GiB on the planned
8GiB VPS, leaving host headroom; CPU quotas overlap, so measured capacity is still
required. Do not increase worker counts or lower disk/memory guards.

## Required owner inputs and blockers

| Input | Required decision/evidence |
|---|---|
| Deployment authority | Explicit approval of this release, target VPS and private Vercel project; no AI/payment approval implied |
| Domain | Owned site domain, exact frontend/API hostnames, custom Vercel domain and approved DNS change |
| SSH | VPS address, non-root sudo operator, key file location, independently verified host fingerprint, allowed source CIDR, rescue access |
| Host coexistence | Verify Ubuntu24.04, Docker/Compose, memory/disk, routes and existing Caddy/SSLH/listeners; approve8443/8444 and subnet172.30.70.0/24 or coordinated replacements |
| Vercel | Team/project IDs, reviewer membership, All Deployments authentication protection, Node22/Corepack build environment |
| Images | Reviewed app, Nginx and backup-tools registry digests, credentials and vulnerability/package review; no mutable tags |
| Private files | Independent DB passwords/URLs, API TLS chain/key and renewal method, backup pgpass/age recipient; never paste secrets in chat |
| Accounts | Approved invite-only reviewer creation and first-admin provisioning; see the explicit implementation blocker below |
| Recovery | Off-server destination/key/fingerprint, offline age identity custodian, approved retention/RPO/RTO, scratch capacity and tested alerts |

Production first-admin/reviewer provisioning is now implemented through separate
operator-approved single-use invites; see the linked follow-up for exact commands,
identity/delivery approvals and recovery behavior. No production account is created
here. Keep the local acceptance bootstrap/evidence unchanged and use a new staging
database. Public registration/email remain disabled; no direct SQL role/verification
shortcut is authorized. Owner roster, identity evidence and delivery channel remain inputs.

## Artifact and environment preparation (future approved execution)

Review the complete uncommitted application changes including Milestone5 files.
Do not use `git archive HEAD`: it omits the implemented uncommitted feature files.
Build a reviewed release snapshot, excluding `.env*`, `.git`, `.venv`, `.tools`,
`var`, private mounts, acceptance receipts, `__pycache__`, credentials and keys.
Backend runtime image COPY lists already omit acceptance scripts and receipts.
Install that backend snapshot under `/opt/zoclip`; commands below run from there.
Frontend CLI commands run **only from frontend/**, never repository root.

Host prerequisite: approved official Docker Ubuntu repository/Engine/Compose and
Python3/OpenSSH. Installation/security updates must be reviewed for the existing
host; follow the official Docker Ubuntu instructions, not a blind curl shell.
After approval, inspect before changing services or firewall:

```sh
ssh -i SET_KEY_FILE -o StrictHostKeyChecking=yes SET_SSH_USER@SET_VPS_IP
lsb_release -ds
free -m
df -h / /var/lib/docker
sudo ss -lntup
ip route
docker version
docker compose version
```

Confirm SSH key access in a second session before hardening sshd. Validate with
`sudo sshd -t`; retain rescue/original access. Approve SSH-only inbound source rules
for both IPv4/IPv6 without disrupting existing Caddy/SSLH or other services. Do
not open API/DB/Redis ports. Independently verify Docker loopback publication;
UFW alone does not establish Docker isolation.

Approved image build/publish on a capable release builder, not this RAM-limited PC:

```sh
cd SET_REVIEWED_BACKEND_SNAPSHOT
docker buildx build --platform linux/amd64 -t SET_REGISTRY/zoclip-app:SET_RELEASE --push .
docker buildx build --platform linux/amd64 -f deploy/Dockerfile.ops -t SET_REGISTRY/zoclip-ops:SET_RELEASE --push .
docker buildx imagetools inspect SET_REGISTRY/zoclip-app:SET_RELEASE
docker buildx imagetools inspect SET_REGISTRY/zoclip-ops:SET_RELEASE
```

These uploads also require future explicit approval. Record reviewed registry
manifest digests and package/SBOM/scan evidence. Existing backup Dockerfile pins
Debian packages: rebuild must confirm availability and security; never silently
remove pins to make a failing build pass. Nginx digest must also be supplied and
reviewed. This preparation did not build/pull/push container images.

On approved VPS:

```sh
cd /opt/zoclip
sudo install -d -m 0700 /etc/zoclip/private
sudo install -d -o 10001 -g 10001 -m 0700 /var/backups/zoclip
sudo install -m 0600 deploy/private-staging.env.example /etc/zoclip/staging.env
sudoedit /etc/zoclip/staging.env
```

Replace every SET_* placeholder, preserving all private profile flags. Metadata
contains origins, directories, images and ports, never passwords. Follow
[DEPLOY_CONTABO.md](DEPLOY_CONTABO.md#files-images-and-secrets) for the ten private
files, escaping and UID readability: root-owned parent0700, individual bind-secret
files0444 inside that inaccessible parent, never mount the directory. DNS-01 TLS
for the API avoids opening public80/443; owner chooses the DNS challenge tool,
credential storage and renewal hook. Certificate must cover the real API hostname.
Do not use self-signed staging TLS or disable verification. No provider, Google,
payment, JWT-signing or fabricated CSRF secret is required: sessions are opaque
hashed DB tokens and CSRF tokens are hashed in their existing session rows.

## Database, Redis, migration and start

Use a NEW isolated staging database/volumes, not acceptance or production data.
The existing empty-volume init creates bootstrap, schema-owner migrator and
non-owner runtime roles. Runtime has no DDL/Alembic writes; migration reapplies
append-only table privileges without disabling financial triggers. Do not run
empty-volume initialization against an existing database. The blocker follow-up
adds invite migration8c42ab719e30; no acceptance schema is migrated.

Define this shell helper for all manual operations (metadata/private files stay
on the server; do not print resolved Compose config):

```sh
cd /opt/zoclip
dc() { sudo docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml -f deploy/compose.private-staging.yaml "$@"; }
sudo python3 deploy/manage.py plan --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private
dc pull
dc --profile tools pull backup
```

Read-only plan validates publication, closed integrations, internal networks,
proxy profile and all three reviewed image digests. The proxy health check and
post-start `nginx -t` below validate its configuration with API service DNS
available, before reviewer access. Do not ignore TLS/permission/syntax errors.

After release review create `/etc/zoclip/rollout-approved.json` mode0600, containing
the exact project/image plus either `new_empty_database:true` for a genuinely new
empty database, or `backup_verified:true` with separately recorded verified backup
manifest. Never set a backup assertion without actual evidence. This marker does
not replace deployment approval. Example new installation metadata:

```json
{"project":"zoclip-private","image":"SET_REGISTRY/zoclip-app@sha256:SET_DIGEST","new_empty_database":true,"schema_compatible":true}
```

```sh
sudo python3 deploy/manage.py up --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc ps
dc exec -T api alembic current
dc exec -T api alembic heads
dc exec -T api alembic check
dc exec -T redis redis-cli ping
dc exec -T redis redis-cli CONFIG GET appendonly appendfsync maxmemory-policy
dc exec -T worker-ai python -m zoclip.ops.health worker
dc exec -T worker-render python -m zoclip.ops.health worker
dc exec -T maintenance python -m zoclip.ops.health maintenance
dc exec -T db psql -U zoclip_bootstrap -d zoclip -v ON_ERROR_STOP=1 -Atc 'BEGIN READ ONLY; SELECT breaker FROM system_limits WHERE id=1; SELECT version_num FROM alembic_version; COMMIT;'
dc exec -T proxy nginx -t
dc stats --no-stream
free -m
df -h / /var/lib/docker
```

The rollout controller stops writers, starts DB/Redis, migrates with the schema
owner and starts healthy workloads. On failure keep them stopped; diagnose,
never retry migrations blindly. Compare actual Alembic current/heads; known
repository head is now8c42ab719e30. Readiness probes DB/schema and Redis, worker probes
check RQ heartbeat and maintenance checks its120s heartbeat.

Redis uses its named data volume, AOF with appendfsync everysec and noeviction,
192MiB maxmemory inside256MiB ceiling. Monitor AOF rewrite disk/memory and errors.
Redis is transport, never ledger truth; approximately the last second of AOF
writes can be lost on failure. PostgreSQL outbox/checkpoints drive recovery.
Do not load a stale Redis snapshot and blindly replay work.

## Boot supervision, maintenance and alerts

Install base units AND M6 drop-ins so reboot/backup/monitor retains the profile:

```sh
sudo install -m 0644 deploy/systemd/zoclip-private.service deploy/systemd/zoclip-monitor.service deploy/systemd/zoclip-monitor.timer deploy/systemd/zoclip-backup.service deploy/systemd/zoclip-backup.timer /etc/systemd/system/
sudo install -d /etc/systemd/system/zoclip-private.service.d /etc/systemd/system/zoclip-monitor.service.d /etc/systemd/system/zoclip-backup.service.d
sudo install -m 0644 deploy/systemd/zoclip-private.service.d/private-staging.conf /etc/systemd/system/zoclip-private.service.d/
sudo install -m 0644 deploy/systemd/zoclip-monitor.service.d/private-staging.conf /etc/systemd/system/zoclip-monitor.service.d/
sudo install -m 0644 deploy/systemd/zoclip-backup.service.d/private-staging.conf /etc/systemd/system/zoclip-backup.service.d/
sudo systemd-analyze verify /etc/systemd/system/zoclip-private.service /etc/systemd/system/zoclip-monitor.service /etc/systemd/system/zoclip-backup.service
sudo systemctl daemon-reload
sudo systemctl enable zoclip-private.service
sudo python3 deploy/check.py --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --backup-dir /var/backups/zoclip --certificate /etc/zoclip/private/tls_certificate
```

Boot resume starts existing containers without rerunning migration. Enable the
monitor timer only after configuring/test-delivering an approved OnFailure alert.
It checks services,5-minute429 spikes, certificate expiry, stale backups and the
existing application monitor. No automatic paid request retry. Backup timer is
disabled until the staffed quiesce/copy/verify/resume procedure is approved.

## Private media, retention and backups

Only application-authenticated owner-scoped endpoints serve media, never Nginx
static aliases or a Vercel public directory. Existing reservation gates preserve
4GiB/120-minute input cap,8MiB streamed parts,16KiB JSON bodies,20GiB disk headroom,
40GiB retained/reserved pool, pending10, ingestion2, processing1 per user. Maintenance
enforces24h incomplete-upload TTL and7-day media retention. These technical maxima
must be disclosed/approved with privacy and backup retention policy before use.

100GB VPS disk cannot hold the maximum working media set plus the existing backup
scratch requirement (20GiB plus twice media+DB). Owner must approve smaller actual
staging usage or separate encrypted-backup scratch capacity; do not reduce guards.

```sh
sudo python3 deploy/manage.py backup --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc run --rm --no-deps backup verify --manifest SET_EXACT_MANIFEST.json
```

Backup stops all writers, streams pg_dump+media to age ciphertext, writes checksummed
manifest last and **leaves writers stopped**. Transfer exactly the manifest and
its two ciphertext files to the approved off-server destination using the strict
host-key commands in [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md). Record remote hashes,
perform a separate empty-target authenticated decrypt/restore drill with the
offline identity, validate schema/data/financial invariants and record RPO/RTO.
Only after verified copy/operator review resume:

```sh
sudo python3 deploy/manage.py resume --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
```

No automatic backup deletion. Nightly/seven-daily/four-weekly retention and24h
RPO/4h RTO in the older guide are proposals requiring owner approval and actual
off-server restore evidence, not implemented service guarantees.

## Vercel and reviewer tunnel (future approved execution)

Create/link a dedicated CLI project whose uploaded source root is the frontend
snapshot itself: Vercel Root Directory is unset/`.` for these commands, not a
second nested `frontend`. Use Node22, the pinned packageManager via Corepack and
the existing reviewed lockfile. `vercel.json` selects frozen
install and the validated webpack production build. Configure public-only values
from `frontend/deploy/private-staging.env.example` for Preview (and Production
before any later promotion). No backend secrets or provider credentials in Vercel.
Set **Vercel Authentication / All Deployments**, invite approved reviewers, disable
bypass/share exceptions, and disable Vercel Toolbar injection/analytics. Standard
Protection alone excludes production custom domains. Confirm protection on custom,
generated and old URLs from a signed-out client before inviting reviewers.

On an adequately resourced release builder with a reviewed installed Vercel CLI:

```sh
cd SET_REVIEWED_FRONTEND_SNAPSHOT
vercel login
vercel link --project SET_PRIVATE_PROJECT --scope SET_TEAM
vercel env add NEXT_PUBLIC_PRIVATE_STAGING preview
vercel env add NEXT_PUBLIC_ENABLE_REGISTRATION preview
vercel env add NEXT_PUBLIC_ENABLE_ANALYTICS preview
vercel env add NEXT_PUBLIC_STAGING_SITE_DOMAIN preview
vercel env add NEXT_PUBLIC_APP_ORIGIN preview
vercel env add NEXT_PUBLIC_API_ORIGIN preview
vercel env add NEXT_TELEMETRY_DISABLED preview
vercel pull --environment=preview
corepack pnpm install --frozen-lockfile
vercel build
vercel deploy --prebuilt
vercel alias set SET_NEW_DEPLOYMENT_URL SET_FRONTEND_HOST
```

Enter exact reviewed template values interactively. Do not use the generated
vercel.app address for application login: CORS/CSRF deliberately accepts only the
custom frontend origin. Domain attachment/DNS/alias changes are future approved
actions. First validate Node22/frozen install/build; local verification used
installed Node20.18 (supported by installed Next) and existing dependencies, so
Node22 fresh-install/Vercel packaging parity remains unverified. If local memory
is limited, the guarded `pnpm run build:verify` refuses below1536MiB initial RAM
or2GiB disk and stops its own tree below256MiB; never disable that guard. It does
not create Vercel prebuilt artifacts. Public variables are baked into bundles:
rebuild for real domains; do not upload this task's placeholder `.next` output.

Each reviewer verifies the SSH host fingerprint, then runs (OpenSSH on Windows or
Unix; keep this process open):

```sh
ssh -N -i SET_KEY_FILE -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:8443:127.0.0.1:8443 SET_SSH_USER@SET_VPS_IP
```

Owner-authorized local hosts entry maps **only** `SET_API_HOST` to127.0.0.1
(`/etc/hosts` or Windows system32/drivers/etc/hosts). Frontend resolves normally
to Vercel. Use real API hostname, HTTPS certificate and8443 throughout; do not
substitute localhost origins, insecure TLS or wildcard CORS. Validate without
authentication/provider calls:

```sh
curl --fail --resolve SET_API_HOST:8443:127.0.0.1 https://SET_API_HOST:8443/health/live
curl --fail --resolve SET_API_HOST:8443:127.0.0.1 https://SET_API_HOST:8443/health/ready
curl -i --resolve SET_API_HOST:8443:127.0.0.1 https://SET_API_HOST:8443/api/v1/admin/dashboard
```

Expect200/200/401. Check browser session cookie Secure/HttpOnly/SameSite=Lax,
host-only scope, credentialed exact-origin CORS and POST CSRF Origin+token checks.
Vercel-authenticated reviewer still needs a separate verified ZoClip account;
customer must receive403 from admin APIs and permission-denied UI. Validate billed
views only against actual staging data; never seed fake payment success or credits.
Chrome's local-network permission can gate public Vercel-to-loopback requests:
reviewer must grant it for this trusted frontend; test the actual supported browser.
Do not disable browser protections or expose the API to avoid a tunnel failure.
This browser/TLS/access check remains unrun, as requested for this PC.

## Rollback, failure and recovery

Record previous app/ops/proxy digests, frontend deployment URL/alias, schema head,
reviewed env metadata and verified backup manifest before each change. Code rollback
requires previous code compatible with CURRENT schema and approved metadata matching
the previous exact app image plus `backup_verified:true`, `schema_compatible:true`:

```sh
sudo python3 deploy/manage.py rollback --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --previous-image SET_PREVIOUS_APP_AT_SHA256 --execute-local
vercel alias set SET_PREVIOUS_DEPLOYMENT_URL SET_FRONTEND_HOST
```

Recheck All Deployments protection and origins after alias rollback. Incompatible
DB rollback means stop writers and restore to **new empty** DB/media targets per
BACKUP_RECOVERY.md, reconcile ledger/outbox/erasure intents and uncertain work, then
review promotion. Never `down -v`, reset provider guards, downgrade finance schema,
overwrite active volumes or replay UNKNOWN work. All recovery keeps AI/payment
disabled, breaker=true and acceptance authorization untouched.

## Local verification record and limits

- Production webpack build PASS, TypeScript/static pages included. Receipt:
  `frontend/test-results/staging-production-build.json` (ignored); Node20.18,
  heap384MiB, one compiler worker, minimum sampled available RAM1475MiB. Initial
  sandbox compiler spawn EPERM resolved by approved local subprocess execution.
- Backend22 new settings/readonly-breaker/registration/policy/CORS/admin cases and
  24 deployment-fence cases PASS; ten existing config/OpenAPI cases PASS.
- Frontend13 staging configuration/security-header cases PASS. Focused Python
  Ruff/mypy and frontend Oxlint PASS. No heavy full suite/browser/provider test.
- Actual Docker Compose5.5.1 merged configuration/plan PASS using synthetic
  metadata and invalid-domain image references only; no engine/container/image
  operation. This caught/fixed omission of tools-profile backup image validation.
- No DB migration/write, service restart, provisioning, financial change, acceptance
  continuation, deployment, DNS, commit or push performed in this milestone.
- Container builds, Nginx runtime/TLS check, Node22 fresh install, VPS health/resource
  checks, reviewer/admin access and off-server recovery remain future verification.

Account provisioning implementation is complete in the blocker follow-up. Owner
inputs, reviewed image/Node22 builds, private protection and actual target
verification still precede approved deployment/reviewer admission.
Live AI acceptance remains paused; deployment approval alone does not resume it.

References reviewed: [Vercel protection](https://vercel.com/docs/deployment-protection),
[Vercel build](https://vercel.com/docs/cli/build),
[Vercel deploy](https://vercel.com/docs/cli/deploy),
[Vercel alias](https://vercel.com/docs/cli/alias),
[package manager](https://vercel.com/docs/package-managers),
[Node versions](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions),
[Compose merge](https://docs.docker.com/reference/compose-file/merge/),
[Docker Ubuntu install](https://docs.docker.com/engine/install/ubuntu/),
[Chrome local-network access](https://developer.chrome.com/blog/local-network-access).
