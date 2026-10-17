# Selected reviewer transport: WireGuard — 2026-10-15

[Owner-confirmed offline verification record](WIREGUARD_OFFLINE_VERIFICATION_2026-10-15.md):
preparation passes; real VPN/browser/HTTPS checks await an approved deployment.

Owner selected reviewer WireGuard VPN, retaining SSH for operations. This replaces
the earlier reviewer SSH-tunnel design. No service/key/account was created or
installed; no server, firewall, DNS, provider or deployment action was performed.
These are templates and future commands requiring explicit deployment approval.

## Exact path and isolation

Reviewer browser → encrypted WireGuard connection → **VPN-interface-bound TCP
socket** → existing Contabo127.0.0.1 HTTPS proxy → internal Python API. HTTPS
terminates at the existing container Nginx using the real API hostname certificate;
the host socket proxy forwards encrypted bytes only. Vercel serves the UI and
never joins the VPN or handles API cookies/upload bodies. Same-site app/API domain,
cookie, CORS, CSRF, RBAC and financial controls remain unchanged.

Docker Compose STILL publishes only loopback8443/8444. Its publication guard is
unchanged. Do not add a Docker VPN/public port or bypass that guard. A separate
systemd socket binds the single RFC1918 VPN server IPv4 address, uses
BindToDevice=wg-zoclip and FreeBind=no, and depends on WireGuard, firewall and
the existing application boot unit. The late socket has explicit shutdown/boot
dependencies to avoid default sockets.target/basic.target ordering cycles.
systemd-socket-proxyd forwards only to127.0.0.1 at the reviewed API HTTPS port,
with32 concurrent connections and64MiB RAM ceiling. Account/provider limits are
not changed. Reviewers need neither SSH accounts nor operator SSH private keys.

Per-device WireGuard public keys authorize distinct peer/32 addresses. Client
AllowedIPs routes only the server VPN IP/32; public Vercel/DNS traffic uses the
client's ordinary Internet connection. No default route, NAT, IP-forwarding
enablement, peer-to-peer route or Docker network route is configured.

The dedicated nftables inet table allows only approved peer IPs arriving on the
WireGuard interface to the VPN API TCP port. It drops other VPN host traffic and
both directions of VPN forwarding before Docker's normal forwarding acceptance.
It also drops attempts to reach that VPN API address from other interfaces.
This covers IPv4/IPv6 forwarding; no reviewer IPv6 address is configured. Reload
atomically replaces only this project's table, never flushes the global ruleset.
WireGuard depends on successful firewall initialization; stopping the firewall
unit retains its rules. The socket binds to the interface independently of filtering.

## Owner inputs before rendering or installation

- A dedicated non-overlapping RFC1918 /24 through /30, server address and unique
  reviewer addresses; review Contabo, Docker, operator/reviewer LAN and other VPN
  routes. Renderer excludes default Docker172.30.70.0/24 plus supplied exclusions;
  it cannot discover remote/reviewer route conflicts. Exclude connected routes,
  not the default0.0.0.0/0 route. Confirm wg-zoclip does not collide with an existing link.
- VPS endpoint, approved UDP port (template51820), source CIDRs where practical,
  WireGuard/firewall package approval and existing firewall coexistence review.
- API HTTPS port matching STAGING_HTTPS_PORT (template8443), distinct owned app/API
  hostnames and valid DNS-01 API certificate/renewal. No domain is selected here.
- Per-device public-key roster, secure configuration delivery and removal owner.
  Generate private keys on each endpoint; never paste them in chat or repository.
  Vercel access and ZoClip first-admin/reviewer invitation remain separate gates.

## Generate reviewable templates locally

`deploy/prepare_wireguard.py` validates only nonsecret addresses/ports and renders
placeholders, systemd units, firewall policy and SHA-256 manifest. It cannot
install, call systemd/nft/wg, contact a VPS, generate keys or change Compose.
It refuses an existing output directory/files. Replace SET_* arguments first:

```sh
python3 deploy/prepare_wireguard.py --server-cidr SET_SERVER_IPV4_WITH_PREFIX --reviewer-address SET_REVIEWER_1_IPV4 --reviewer-address SET_REVIEWER_2_IPV4 --exclude-cidr SET_OTHER_CONNECTED_CIDR --udp-port SET_WG_UDP_PORT --api-port SET_API_HTTPS_PORT --output-dir SET_NEW_REVIEW_DIRECTORY
```

Omit optional second reviewer/exclusion when absent. Review each generated file
and manifest. The recorded local CLI smoke used synthetic addresses and contains
only placeholders under ignored var; it is not an owner-selected live subnet.

## Future approved installation on Ubuntu24.04

First approve the existing host/package/firewall changes, preserve rescue and
operator SSH access, and install/review WireGuard tools and nftables from the
approved Ubuntu repositories. Verify systemd255-compatible options/binary paths.
The existing M6 two-file application Compose and systemd drop-ins remain required.
Build/provision private staging under its existing runbook before starting the
VPN API socket. Never copy local acceptance DB, provider credentials or guards.

Generate keys independently on the VPS and each reviewer endpoint, in private
directories. Linux pattern (execute on each correct endpoint, not centrally for
reviewers); Windows reviewers use the official WireGuard client's local tunnel
creation/import. Only public keys are exchanged and independently verified:

```sh
umask 077
wg genkey > private.key
wg pubkey < private.key > public.key
```

Do not use shell tracing or print private files. Fill server/reviewer key
placeholders privately in0600 configuration files. Server peer AllowedIPs must
remain each reviewed device/32; client AllowedIPs must remain server-IP/32. Endpoint
is the real VPS address/approved UDP port; client keepalive25s supports NAT.
No demo transport, shared private key, SaveConfig or PostUp routing scripts.

Future host file installation, from the reviewed generated directory:

```sh
sudo install -d -m 0700 /etc/wireguard /etc/zoclip/wireguard
sudo install -m 0600 wg-zoclip.conf.example /etc/wireguard/wg-zoclip.conf
sudoedit /etc/wireguard/wg-zoclip.conf
sudo install -m 0600 reviewer-guard.nft /etc/zoclip/wireguard/reviewer-guard.nft
sudo install -m 0644 zoclip-reviewer-firewall.service zoclip-vpn-api.socket zoclip-vpn-api.service /etc/systemd/system/
sudo install -d /etc/systemd/system/wg-quick@wg-zoclip.service.d
sudo install -m 0644 wg-quick-firewall.conf /etc/systemd/system/wg-quick@wg-zoclip.service.d/reviewer-firewall.conf
sudo systemd-analyze verify /etc/systemd/system/zoclip-reviewer-firewall.service /etc/systemd/system/zoclip-vpn-api.socket /etc/systemd/system/zoclip-vpn-api.service
sudo systemctl daemon-reload
```

Review firewall policy BEFORE enabling WireGuard. In the existing host and
Contabo firewalls allow the approved **WireGuard UDP** listener, restricted to
reviewer source ranges if feasible. Permit approved peer addresses to the API port
only on wg-zoclip in any additional host input-policy chain. A restrictive host
chain can still reject traffic accepted by this project's earlier chain; test
coexistence. Keep public TCP API/DB/Redis and reviewer VPN SSH/other services denied.
No blanket UFW reset, global nftables flush or replacement of other services is
authorized by this runbook. Do not enable flow offload/alternate routing that
bypasses the VPN forward guard. No public API A/AAAA record is needed.

```sh
sudo systemctl enable --now wg-quick@wg-zoclip.service
sudo systemctl enable --now zoclip-vpn-api.socket
sudo systemctl is-active zoclip-reviewer-firewall.service wg-quick@wg-zoclip.service zoclip-vpn-api.socket
sudo ip address show dev wg-zoclip
sudo nft list table inet zoclip_reviewer_vpn
sudo ss -lntup
```

If a unit/syntax/permission/bind check fails, keep reviewer access closed. Do not
change bindings to0.0.0.0, enable forwarding or disable safety guards to recover.
Monitor these units/rules and route changes; integrate failure notifications with
the existing owner-approved alert channel. Test restart/reboot and firewall-manager
reload: guard must still precede WireGuard/socket access. No such target validation
was possible or performed on this Windows preparation machine.

## Reviewer DNS, browser verification and revocation

Use managed per-device hosts mapping or approved split DNS:
`SET_SERVER_VPN_IPV4 SET_API_HOST`. Frontend keeps resolving to Vercel. Verify DNS
ownership/real TLS/SNI; never use an IP/localhost browser API origin or disable
certificate validation. Reviewers activate their own WireGuard tunnel, authenticate
to Vercel and visit the custom frontend `/private-access`. Its explicit browser
readiness button must succeed with local-network permission where required.
Do not assume VPN handshake, curl or Vercel authentication proves browser access.
Then accept the private ZoClip invitation and perform normal login/RBAC/CSRF checks.

```sh
curl --fail https://SET_API_HOST:SET_API_HTTPS_PORT/health/ready
```

Admission also requires: unknown peer denied, customer admin403/admin allowed,
VPN peer cannot reach SSH/DB/Redis/container networks/other peers, API unavailable
with VPN disconnected, and independent external IPv4/IPv6 checks show no public
API TCP listener. Monitor actual VPN/proxy resources; the extra host proxy ceiling
is64MiB, not a measured usage claim. AI/spending/payments remain disabled.

Revoke Vercel access and the ZoClip reviewer through existing audited procedures,
then remove the individual WireGuard peer from server runtime AND its persistent
0600 configuration. Regenerate/review the firewall peer set excluding that device
and atomically reload the dedicated table. An approved operator can use
`sudo wg set wg-zoclip peer SET_REVOKED_PUBLIC_KEY remove`; do not log private keys.
Remove its private DNS/hosts profile and verify old sessions/network access denied.
WireGuard key removal is per device; removing only a hosts entry is not revocation.

For fail-closed rollback stop zoclip-vpn-api.socket AND zoclip-vpn-api.service, then
stop the WireGuard unit after reviewing other peer use. Retain firewall filtering
and backups/audit history. Do not automatically fall back to reviewer SSH or public
API access. Operator SSH/rescue remains separate. Restore retains the invite epoch
rotation and audited account/session reconciliation requirements.

References: [WireGuard](https://www.wireguard.com/quickstart/),
[systemd255 socket options](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.socket.xml),
[socket proxy](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd-socket-proxyd.xml),
[nftables semantics](https://netfilter.org/projects/nftables/manpage.html),
[Docker publication](https://docs.docker.com/engine/network/port-publishing/),
[Chrome network permission](https://developer.chrome.com/blog/local-network-access).
