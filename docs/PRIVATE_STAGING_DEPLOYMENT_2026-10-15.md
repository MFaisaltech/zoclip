# Private staging deployment — 2026-10-15

Owner authorized this deployment and the first Windows reviewer device. This is
private staging, with browser/account acceptance still requiring the owner. It
does not resume live AI acceptance or authorize spending, payments or public launch.

## DNS, TLS and frontend

- Both Namecheap authorities and Cloudflare/Google recursive DNS matched the exact
  CNAME and live TXT challenge. Namecheap Host `_acme-challenge.api.zoclip` correctly
  expands to `_acme-challenge.api.zoclip.technabeel.com`. Observed authoritative TTL
  was 1799 seconds (approximately30 minutes), despite the proposed5-minute TTL.
- The active Let's Encrypt DNS-01 request completed successfully. The certificate
  covers only `api.zoclip.technabeel.com`, chains successfully to trusted roots,
  and expires2027-01-13. No public API A/AAAA record or HTTP challenge was added.
- `https://zoclip.technabeel.com` points to deployment
  `dpl_DsBysqs6mvayjP39RAmKcxrW5uiS`. Node22/frozen pnpm12.3.4 install,
  webpack production build and TypeScript validation passed on Vercel.
- Fixed the missing pnpm environment-lock document. The original application
  dependency-lock document was verified byte-for-byte unchanged after trimming
  outer whitespace; frozen install remains enabled. No dependency versions changed.
- Vercel Authentication remains `deploymentType=all`; preview/production feedback
  injection is disabled. Signed-out requests to custom and generated deployment
  URLs redirect to Vercel authentication. The former `zoclip-nine.vercel.app`
  address returned404. No bypass credentials/exceptions were created.
- Portfolio, email, nameservers and unrelated DNS/infrastructure were not changed.

## Private API and VPN diagnosis

The exact API origin is **`https://api.zoclip.technabeel.com:18443`**, as baked into
the frontend. Port443 belongs to pre-existing SSLH and was not modified. Ping and
VPN access to443 are intentionally denied; neither is an API readiness test.

The PC generated its reviewer key locally using the installed X25519 library;
the server received only the public key. The owner installed/activated WireGuard
and added the local hosts mapping manually. Inspected Windows routes had LAN
`192.168.1.0/24`; the selected VPN subnet `10.203.253.0/29` did not overlap those
routes, Contabo routes or Docker172.17.0.0/16 /172.30.70.0/24.

- Server `wg-zoclip`:10.203.253.1/29; authorized PC:10.203.253.2/32.
- Client routes only10.203.253.1/32; existing Windows network settings were not
  modified by the agent. No default-route, DNS-server, NAT or forwarding change.
- A current authenticated WireGuard handshake and transfer counters were observed.
  A counter-only diagnostic rule recorded five TCP packets from the PC on18443.
- The dedicated nftables table permits only that peer's API HTTPS on the VPN
  interface, drops other VPN host access, and drops VPN forwarding both ways.
  Existing global rules were not flushed or replaced.
- Docker publishes proxy HTTPS/admin only at127.0.0.1:18443/18444. The systemd
  socket binds `10.203.253.1%wg-zoclip:18443` and forwards encrypted bytes to
  loopback18443. It depends on the WireGuard/firewall/application units.
- The initial connection refusal was the stopped staging workload/socket during
  backup/security review, plus testing443 instead of18443. Starting the reviewed
  workload and VPN-bound socket fixed the refusal; no public443 route was added.

Actual HTTPS from the Windows PC over its activated VPN, with normal certificate
validation and hostname/SNI: live200, ready200, anonymous admin401, docs404. CORS
returned exactly `https://zoclip.technabeel.com`. VPN probes to22,443,18444,5432 and
6379 failed. Public IPv4 probes to18443,18444,5432 and6379 failed. Server bind
inspection showed no public/IPv6 staging TCP listener. The PC has no external
IPv6 route, so independent public IPv6 probing remains unverified. Unknown-peer,
second-peer, reboot and actual signed-in browser isolation checks remain unrun.

## Runtime and security refresh

Seven steady services reached healthy status. Alembic head is8c42ab719e30 and
`alembic check` reported no new upgrade operations. Runtime/migration roles remain
separate. Redis AOF/everysec/noeviction and Nginx configuration checks passed.

Closed flags and internal networks were verified on API and all workers:
AI=false, breaker=true, registration=false, payments=disabled, live payments=false,
trial credits=false, email=disabled, external imports empty, provider keys empty.
Provider usage, billing orders, wallets and credit transactions remained zero.
FFmpeg in the refreshed image generated and ffprobe validated a real1-second
H.264/AAC fixture. This is not full render quality or paid-provider acceptance.

Original release: `staging-20261015-d639751916eb`. Security refresh:
`staging-20261015-security1`, preserving application code/locked dependencies/schema.
Original files/images and pre-refresh metadata were retained for reviewed rollback.

| Image | Deployed immutable reference |
| --- | --- |
| App | `zoclip-private-app@sha256:d3485f5f87f592be57d7fc6a47e41419736fbedd30f425f6050ce20cffd3be01` |
| Proxy | `nginx@sha256:ed84151ed2d47ef93c0939eb9b9754c6990db6092cd2081e11988a47a83d47ea` |
| Backup tools | `zoclip-private-ops@sha256:8db3182a32f032141ec3a9bd0379ddce75ddb2c7089e2249c9a86261a31eec9c` |

The app base moved to pinned Python3.12/Debian13; backup tools use pinned
PostgreSQL17/Debian13 and exact reviewed package versions. Removed the unused
gosu binary from the backup image. Proxy moved to pinned official Alpine Nginx.
Existing runtime users, read-only filesystems, caps, quotas and private bindings
were retained. No host operating-system or existing portfolio services upgraded.

Checksum-verified Trivy0.76.0 scanned the images. Reports are retained privately
under `/opt/zoclip-private/build-evidence/staging-20261015-security1/scans`.

| Image | Original high/critical | Refreshed high/critical |
| --- | --- | --- |
| App |258/8 |212/1 |
| Proxy |147/10 |0/0 (one medium remains) |
| Backup tools |101/5 |91/2 |

These are scanner counts, not a claim of exploitability or zero vulnerabilities.
No remaining high finding in these candidate reports had an available fixed
version. Remaining critical labels concern libxml2 and the unused backup-image
OpenSSH client. Debian classifies both as minor issues without a stable-release
security update: [CVE-2026-6653](https://security-tracker.debian.org/tracker/CVE-2026-6653),
[CVE-2026-60002](https://security-tracker.debian.org/tracker/CVE-2026-60002).
The libxml2 issue is not claimed unreachable in media handling. Authentication,
one authorized VPN peer, no external imports/egress, resource limits and container
restrictions remain essential; further remediation/review precedes public release.

After the final restore, the existing workload was resumed without migration.
All seven steady services were healthy, all four relevant systemd units were
active, final closed flags/internal networks passed, and the host check returned
`alerts:[]`. Running-state Windows VPN HTTPS/CORS checks passed again; an untrusted
Host returned400, and public18443/18444 remained unreachable. Custom/generated
frontend URLs still redirected signed-out requests to Vercel authentication.

Focused offline checks:52 backend private-staging cases and24 frontend staging
configuration/access cases passed. Actual Vercel build and runtime checks above
are separate deployment evidence; no paid calls or acceptance changes occurred.

## Admin invitation and recovery

The owner explicitly selected the first-admin email. The audited CLI issued one
pending invitation (`44bf4cdc-61f7-4233-a0e6-68603b983cdb`) with identity-evidence,
target and approval hashes. Raw token was delivered by pinned SSH into the local
private folder and never printed. It expires2026-10-15 at17:01 PKT. The owner must
set their password and redeem it normally; no verified/admin activation or credits
were fabricated. Before redemption the pending account remains an unverified
customer; first-admin elevation occurs only in the existing audited redemption.

Local private folder:
`D:\ZoClip-Project\backend\var\deployment-execution\local-private`.
Inheritance is disabled; only the owner Windows account and SYSTEM have access.
All files are Git-ignored and outside the uploaded frontend snapshot.

- `zoclip-reviewer.conf`: private WireGuard import profile, kept on this PC.
- `first-admin-invitation.txt`: single-use private invitation URL; do not share.
- `backup-recovery.agekey`: recovery identity, generated locally using checksum-
  verified official age1.3.2; never uploaded to Contabo. Copy it into an encrypted
  password manager or encrypted offline removable storage, separately from the
  backup ciphertext. Keep an independently protected second recovery copy.
- `backups`: encrypted database/media files and checksum manifests.

The initial quiesced baseline was copied to this PC, hash-verified and restored
with authenticated age EOF into a new loopback-only PostgreSQL17 cluster. Schema,
breaker, zero initial financial/provider rows and empty media passed. Existing
local databases were not modified; the scratch cluster was stopped afterward.
The final post-invitation snapshot is `20261015T110818-e2b5ffcb.json`, manifest SHA256
`5a8e1087f89680057290a4477c8244d5e76cd510c20fa9b5ed89fea319968dd9`.
It was copied to this PC, its manifest/ciphertext hashes matched, and a second
authenticated local PostgreSQL17 restore passed in9.67seconds. The restored
pending account/invite, both staging audit events, zero financial/provider rows
and empty media were verified. The scratch cluster was stopped afterward; no
recovery identity went to the application host. Any future restored environment
must rotate its invite epoch,
retire sessions and reconcile authority before admission, per the runbook.

Backup/alert scheduling, retention and RPO/RTO have not been invented or activated;
this is a supervised staging backup. Manual DNS-01 renewal requires a fresh TXT
challenge before certificate expiry; unattended renewal is not configured. Do not
reuse this completed challenge token for a future order or enable HTTP-01/public API.

Owner next steps: visit the protected custom-domain `/private-access` in the actual
browser, run its readiness button (grant local-network permission if prompted),
then open the local invitation file, redeem it and log in. Browser cookie/CSRF,
authenticated admin/customer isolation and VPN-disconnected behavior need actual
browser verification. No production readiness claim is made.
