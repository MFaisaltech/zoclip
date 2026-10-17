# Private staging blocker implementation — 2026-10-14

**2026-10-15 owner selection supersedes reviewer SSH:** use
[WireGuard reviewer preparation and exact host proxy/firewall procedure](WIREGUARD_REVIEWER_ACCESS.md).
Docker remains loopback-only; reviewers use individual VPN keys, SSH is for
operations. Older managed-SSH details below are a superseded alternative, not the
selected deployment procedure. Vercel still has no private API network connection.

This document supersedes the M6 runbook's missing account-provisioning statement.
No production account, invite, deployment, DNS or provider action has been executed.
Only new preserved schemas in the existing separate mock test database were written.
Acceptance database/evidence, local bootstrap and one-shot guards are untouched.

## Audited first admin and reviewer procedures

New migration **8c42ab719e30**, after7b37ea061d28, adds only
`staging_account_invites`. Apply it through the existing approved owner migrator
during a later deployment, never against the acceptance DB. Approval identity,
token hash, target, issuer, purpose and expiry are immutable. Database triggers
permit only one pending→consumed/revoked transition and forbid delete/truncate.
Populated downgrade refuses to discard evidence. Existing ledger/policy/audit
tables and financial triggers are unchanged; runtime cannot delete invite history.

Only `python -m zoclip.ops.provision_staging` can issue/revoke. It requires validated
production/private-staging settings and spending blocked. No issuance HTTP API,
public registration, implicit role linking or automatic credits. The trusted
operator requires owner first-admin approval or an existing active verified admin's
reviewer approval. Retain the exact approved manifest and independent identity
evidence privately; operator OS access is the authority boundary, not possession
of a freely chosen actor UUID. The manifest's SHA-256 is stored in the immutable
audit and invite; approval is bound to DB host/port/name/connection options, exact
app/API origins and an owner-selected `STAGING_INVITE_EPOCH` UUID outside the DB.
Generate that nonsecret UUID for this deployment; rotate it after any restore.
Missing epoch refuses issuance/redemption. Never restore an old epoch from backup.

First-admin issuance is globally serialized: one outstanding invitation and no
existing/historically activated admin. The account remains unverified/customer
with no password until redemption. Only a valid first-admin token atomically
activates the admin role. Bootstrap stays permanently closed after activation,
including if that admin is later disabled/erased. No automatic break-glass reset.

Reviewers always become customers. Issuer must still be active/verified/admin at
redemption. Recipient sets their own Argon2id password through the normal CSRF
session boundary and rate limiter; all old sessions are revoked, no automatic
login occurs. Invalid/expired/revoked/replayed tokens fail. Tokens are random
256-bit values, stored only as hashes in the DB and valid for at most one hour.
Approval must be fresh within15minutes when issued. User's login/session/cookie,
CSRF, owner isolation and admin dependencies are reused unchanged.

### Future operator commands — require explicit provisioning approval

Use the M6 two-file `dc` helper. On the host, prepare a UID10001 private delivery
directory and a separate root-only approval archive (no operation executed here):

```sh
sudo install -d -o 10001 -g 10001 -m 0700 /etc/zoclip/invite-delivery
sudo install -d -m 0700 /etc/zoclip/invite-approvals
dc exec -T api python -m zoclip.ops.provision_staging target
```

The target command prints only a nonsecret target digest and makes no DB connection.
Owner independently verifies identity/email and privately approves this manifest
with real UUID/UTC timestamps and SHA-256 of the retained identity evidence:

```json
{
  "operation_id": "SET_NEW_UUID",
  "purpose": "first_admin",
  "email": "SET_VERIFIED_OWNER_EMAIL",
  "actor_id": null,
  "operator": "SET_AUTHORIZED_OPERATOR",
  "identity_evidence_sha256": "SET_EVIDENCE_SHA256",
  "target_sha256": "SET_TARGET_SHA256",
  "approved_at": "SET_CURRENT_UTC_TIMESTAMP",
  "expires_at": "SET_UTC_TIMESTAMP_WITHIN_ONE_HOUR"
}
```

For reviewers use purpose`reviewer` and the approving ZoClip admin's UUID. Never
promote an existing customer or change their credentials via this procedure.
Make the manifest root-owned0444 within the root-only0700 archive for a single
read-only container mount; retain it unchanged after use. A dedicated delivery
channel/private password manager must be selected by the owner, with verified
recipient and minimal retention. No raw token in chat/commands/logs.

```sh
sudo sha256sum /etc/zoclip/invite-approvals/SET_OPERATION.json
dc run --rm --no-deps -T -v /etc/zoclip/invite-approvals/SET_OPERATION.json:/run/invite-approval.json:ro api python -m zoclip.ops.provision_staging plan --approval /run/invite-approval.json
dc run --rm --no-deps -T -v /etc/zoclip/invite-approvals/SET_OPERATION.json:/run/invite-approval.json:ro -v /etc/zoclip/invite-delivery:/invite-delivery api python -m zoclip.ops.provision_staging issue --approval /run/invite-approval.json --expected-sha256 SET_REVIEWED_APPROVAL_SHA256 --token-output /invite-delivery/SET_OPERATION.token --execute
dc exec -T api python -m zoclip.ops.provision_staging inspect --operation SET_OPERATION_UUID
```

The plan reads/validates the manifest, without DB writes or tokens. Issuance
rechecks all durable authority/financial gates. It creates a0600 exclusive
no-symlink token file, fsyncs it and its private parent **before** committing the
pending account/invite/audit transaction. If delivery-file creation fails, all DB
changes roll back. On any uncertain commit keep the artifact and inspect; never
reissue the same operation or overwrite its token. A committed replay is refused.
If an artifact is lost, explicitly revoke/expire the pending invite, then approve
a NEW operation for the same still-unverified staging account. No active/verified
account can be overwritten. Linux mode/ownership/mount readability still needs
verification on the actual staging host; native Windows execution is refused.

Deliver `https://SET_FRONTEND_HOST/accept-invite#token=PRIVATE_TOKEN` using the
approved private channel. Recipient must first pass Vercel and private API access.
The fragment is removed locally, never auto-submitted and never sent in the page
HTTP request. POST `/api/v1/auth/invite/accept` requires anonymous session, exact
Origin and CSRF token; it receives token/password in its bounded body, never URL.
No role/email/credit choice is accepted from the recipient. Follow with normal login.
Record issuance/activation event IDs without retaining a plaintext token longer
than approved delivery requires; never remove the approval/audit/invite history.

For an unused invite (first-admin owner revocation omits `--actor`; reviewers need
an approving admin) or a redeemed reviewer, use a privately retained revocation
authority record's SHA-256:

```sh
dc exec -T api python -m zoclip.ops.provision_staging revoke --operation SET_INVITE_UUID --actor SET_ADMIN_UUID --authority-evidence-sha256 SET_REVOCATION_EVIDENCE_SHA256 --execute
dc exec -T api python -m zoclip.ops.provision_staging revoke-reviewer --operation SET_REDEEMED_REVIEWER_INVITE_UUID --actor SET_ADMIN_UUID --authority-evidence-sha256 SET_REVOCATION_EVIDENCE_SHA256 --execute
```

Reviewer revocation disables only a provisioned staging customer and revokes all
their sessions atomically, retaining consumed invite/audit/financial history. It
cannot revoke/promote the first admin or unrelated accounts. Access restoration
is not automatic; requires a separately reviewed procedure. Remove corresponding
Vercel grants and individual network keys too. The CLI prints operation/state only.

## Exact private API path and mandatory verification

The earlier owner-selected **managed reviewer SSH tunnels** remain the prepared
transport unless the owner selects a VPN instead. There is **no Vercel-server to
Contabo connection**. The data path is explicitly:

1. Reviewer browser authenticates to Vercel and loads UI at the owned app subdomain.
2. The browser resolves the owned API subdomain to its own127.0.0.1 using a managed
   hosts entry. Its HTTPS requests to that hostname:8443 retain real Host/TLS/SNI.
3. The reviewer's local SSH forward carries TCP to Contabo127.0.0.1:8443, then
   Nginx TLS proxies to internal API:8000. Browser session cookies and CSRF go
   directly to the API; Vercel never handles them or the media upload body.
4. Browser must explicitly permit local-network access where enforced. A tunnel,
   TLS curl probe or Vercel login alone is **not** evidence browser requests work.

This is suitable only for managed reviewers able to run the client, hosts mapping
and supported browser. It is not an ordinary public-preview deployment. Configure
one restricted OS account/key per reviewer, no sudo/Docker membership and no
shell. Review `deploy/sshd-reviewers.conf.example` alongside existing AllowUsers
rules; it permits local forwards only to127.0.0.1:8443, denies remote/socket/agent
forwarding and shell/PTY. In each reviewer's authorized_keys use
`restrict,port-forwarding,permitopen="127.0.0.1:8443"` before their individual public
key. Owner checks current Ubuntu OpenSSH support and validates/reviews the effective
Match-group configuration with `sshd -t`/`sshd -T -C` before reload, preserving
operator/rescue access. Never share the sudo operator's private key with reviewers.
If8443 changes, update PermitOpen, tunnel, DNS-origin metadata and templates together.

```sh
ssh -N -i SET_REVIEWER_KEY_FILE -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:8443:127.0.0.1:8443 SET_REVIEWER_SSH_USER@SET_VPS_IP
curl --fail --resolve SET_API_HOST:8443:127.0.0.1 https://SET_API_HOST:8443/health/ready
```

After hosts/TLS/tunnel configuration, open **the real custom frontend**
`https://SET_FRONTEND_HOST/private-access`. Its explicit button makes one credentialed
browser GET to `/health/ready`, requires a readable200 `{status:"ready"}` response,
rejects redirects/noncanonical frontend addresses, times out and never retries.
Failure blocks the reviewer admission checklist. Then test invitation, login,
cookie flags, a CSRF-protected action, customer403 on admin and admin success.
Close the tunnel and confirm API unavailable. From an external non-tunneled host
verify no API/DB/Redis port exposed. No such network/browser check was executed here.

If owner chooses VPN, the alternative path is browser→reviewer VPN→Nginx on an
approved private VPN interface, with API name resolving to that private IP and
the same public-valid hostname certificate. That requires a separately reviewed
interface binding/firewall/peer configuration; the current profile deliberately
refuses anything except loopback. Vercel still has no private-network access.
If owner requires actual server-to-server requests instead, select/provision a
managed private connector/gateway and a reviewed auth/upload design first. No
unverified Vercel rewrite/localhost fetch is prepared. Do not route8MiB upload
parts through Vercel Functions: their documented body limit is4.5MB.

Sources: [Chrome network permission](https://developer.chrome.com/blog/local-network-access),
[OpenSSH restrictions](https://man.openbsd.org/sshd_config),
[authorized key restrictions](https://man.openbsd.org/sshd),
[Vercel Functions limits](https://vercel.com/docs/functions/limitations).

## Same-site domains and deployment protection

No domain is selected/purchased. Set identical owner-selected site domain and
canonical exact HTTPS origins in backend/frontend templates, with distinct app/API
hostnames (host-only API cookies must not reach Vercel). No wildcard host/origin,
userinfo, path/query, uppercase hostname or explicit default443. Backend accepts
only the API hostname in ALLOWED_HOSTS; CORS accepts only the exact frontend origin,
including nondefault API port in corresponding CSRF configuration. The owner must
verify the site is an actually owned registrable domain, not a public suffix.
Generated vercel.app URLs are protected but are not login/API application origins.
Changing domains requires new frontend build and target-bound invite approvals.

Follow `frontend/deploy/REVIEWER_ACCESS.md` and the prepared official
`vercel-protection.example.json` body: All Deployments Vercel Authentication,
approved project Viewer/access grants, no share/bypass exceptions, analytics or
Toolbar injection. Source files/headers/robots do not activate Vercel protection.
Owner must configure it before upload and verify custom/generated/old URLs deny
signed-out/unapproved users. Reviewer grants are separate at Vercel, transport and
ZoClip layers; revocation applies to all three. See
[Vercel protection](https://vercel.com/docs/deployment-protection) and
[reviewer access](https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication).

## Owner-selectable backup and restoration configuration

`deploy/backup-policy.example.json` is an owner decision record, **not an activated
scheduler or automatic retention/deletion implementation**. Select local encrypted
scratch path (BACKUP_DIR), separate SSH/SCP storage host/user/path/port, verified
host fingerprint and known_hosts file, restricted transfer key, public age recipient
and independent offline identity custodian. A non-SSH destination requires its own
reviewed adapter; do not claim object-storage support. No destination is contacted.

Choose maintenance window UTC, counts/ages for daily/weekly/monthly points, maximum
retention, RPO/RTO, restore drill cadence and failure alert owner. No invented defaults
are activated. Retention deletion is manual/explicitly approved: retain the latest
verified/restorable point, reconcile erasure obligations and never delete source
evidence or backups merely because an unverified replacement exists. Technical
upload/media TTLs remain24h/7days; approve disclosure and backup privacy policy.

The existing backup controller quiesces writers and creates age-encrypted database
and media ciphertext + checksum manifest. Leave writers stopped until a restricted
off-server transfer and checksum verification succeeds. Use the runbook helper with
both Compose files. Exact future commands with owner-selected identifiers:

```sh
sudo python3 deploy/manage.py backup --private-staging --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
dc run --rm --no-deps backup verify --manifest SET_EXACT_MANIFEST.json
sudo scp -P SET_BACKUP_SSH_PORT -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=SET_BACKUP_KNOWN_HOSTS -i SET_BACKUP_KEY SET_EXACT_DB_CIPHERTEXT_PATH SET_EXACT_MEDIA_CIPHERTEXT_PATH SET_BACKUP_USER@SET_BACKUP_HOST:SET_PRIVATE_DIRECTORY/
sudo scp -P SET_BACKUP_SSH_PORT -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=SET_BACKUP_KNOWN_HOSTS -i SET_BACKUP_KEY SET_EXACT_MANIFEST_PATH SET_BACKUP_USER@SET_BACKUP_HOST:SET_PRIVATE_DIRECTORY/
```

Copy ciphertext first, manifest last. Record/compare remote SHA-256s using exact
manifest-listed files and verified host key. Back up reviewed nonsecret release/
environment/approval metadata encrypted; DB/TLS/SSH credentials require the owner's
separate secure escrow. Token delivery files are not backup input. No age private
identity stays on the application server. A full40GiB working set cannot also fit
the existing20GiB+2×(DB+media) backup guard on100GB: supply separate scratch capacity
or cap actual staging usage; do not lower guards.

On a separately approved isolated recovery host, prepare a NEW empty PostgreSQL17
target named with `_restore` suffix, reviewed role/credential setup and an EMPTY
UID10001 media volume. Keep public networking/provider access disabled; never
restore over live volumes. Using the reviewed tools image and private single-file
mounts, the exact container pattern is:

```sh
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 --network SET_ISOLATED_RECOVERY_NETWORK --tmpfs /tmp:rw,noexec,nosuid,size=64m -e PGHOST=SET_RECOVERY_DB_HOST -e PGUSER=SET_RECOVERY_OWNER_ROLE -e PGDATABASE=SET_EMPTY_DATABASE_restore -e PGPASSFILE=/run/secrets/backup_pgpass -v SET_PRIVATE_PGPASS_FILE:/run/secrets/backup_pgpass:ro -v SET_OFFLINE_IDENTITY_FILE:/run/secrets/backup_identity:ro -v SET_CIPHERTEXT_DIRECTORY:/backups:ro -v SET_EMPTY_MEDIA_VOLUME:/restore-media SET_REVIEWED_OPS_IMAGE_AT_SHA256 restore --manifest SET_EXACT_MANIFEST.json
```

The tools image entrypoint runs backup.py; plaintext streams only into the empty
DB/media target. Verify authenticated age EOF, hashes, Alembic revision, ledger/
audit/session state, media ownership, invite consumed/revoked history and erasure
intents. Before bringing any restored API online, replace `STAGING_INVITE_EPOCH`
with a fresh UUID in private deployment metadata and recreate affected containers;
every old raw invitation now fails even if its DB snapshot predates consumption.
Explicitly revoke pending records using retained owner/admin authority; retain
consumed history as consumed. Retire restored sessions before admission through
a reviewed audited recovery transaction and reconcile account status/roles with
off-server authority evidence. Reconcile any post-backup consumption/revocation before promotion: a
backup predating consumption must not resurrect authority. Keep access closed
until that reconciliation is complete. No provider/financial guard reset or
automatic Redis queue replay. Record actual restore elapsed time and recoverable
timestamp; only then review promotion and resume via the existing runbook.

## Exact remaining owner inputs and release condition

| Area | Owner must supply/decide privately |
|---|---|
| Target | VPS IP, approved sudo SSH username/key path, independently verified fingerprint, source CIDRs, rescue access, approved ports/subnet and coexistence review |
| Domains/DNS | Existing/purchased-by-owner registrable site, distinct exact app/API hostnames, DNS account authority and approval for Vercel custom domain/DNS-01 records; no public API A record needed for hosts-only transport |
| TLS | Valid API full chain/key paths, DNS-01 tool/provider credentials stored privately, renewal owner/hook; never self-signed or curl -k |
| Vercel | Team/project IDs, plan/seat feasibility, protection administrator, approved reviewer Vercel accounts and custom domain; Node22/Corepack builder |
| Transport | Confirm managed SSH reviewer clients/individual restricted keys and supported browser permissions, or explicitly select/review VPN alternative |
| App identity | Named first admin/reviewer emails, approving operator/admin, independent identity evidence/delivery channel and deployment invite-epoch UUID; fresh scoped manifests when later authorized |
| Images | Complete reviewed source snapshot including uncommitted feature files, release ID, app/Nginx/backup-tools immutable registry digests, private registry credentials, build/package/scan evidence |
| Backup | Local scratch capacity/path, separate destination/port/user/path/key/fingerprint, age recipient/offline custodian, retention/RPO/RTO/drills/window/alerts and restore reconciliation approval |
| Authorization | Explicit private deployment approval, plus separate production provisioning approval; neither includes AI/payment/acceptance approval |

Implementation blockers are resolved for the prepared managed-SSH design. Private
staging can proceed to an **explicitly approved deployment** after owner inputs,
fresh Node22/image builds and deployment protection configuration. Reviewer
admission additionally requires actual TLS/tunnel/browser/RBAC and restore checks.
If the chosen network model differs, its reviewed configuration is a prerequisite;
never claim an SSH-only API is reachable directly from Vercel or an arbitrary browser.

Focused verification:81 backend cases and36 frontend cases pass; real isolated
PostgreSQL concurrency, transaction/crash/replay/permission cases, migration/model
comparison and populated-downgrade refusal pass. Python Ruff/mypy, frontend
Oxlint/TypeScript, generated contracts and synthetic Compose plan pass. Linux
delivery filesystem and actual reviewer networking remain target checks.
No full suite,
browser automation, live provider test, actual provisioning, DNS, deployment,
commit or push was performed. Existing M6 production-build PASS is historical;
new code receives focused lint/type/API/migration/security checks, not a new build.
