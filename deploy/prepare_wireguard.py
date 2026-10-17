"""Render nonsecret reviewer-VPN templates only. Never installs, starts or contacts services."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path

PRIVATE = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    )
)
INTERFACE = "wg-zoclip"


def render_bundle(server_cidr, reviewers, udp_port=51820, api_port=8443, exclude_cidrs=()):
    server = ipaddress.IPv4Interface(server_cidr)
    network = server.network
    if (
        not 24 <= network.prefixlen <= 30
        or not any(network.subnet_of(private) for private in PRIVATE)
        or server.ip in {network.network_address, network.broadcast_address}
    ):
        raise ValueError("Choose a usable RFC1918 server address in a /24 through /30 subnet")
    for excluded in ("172.30.70.0/24", *exclude_cidrs):
        if network.overlaps(ipaddress.IPv4Network(excluded)):
            raise ValueError("VPN subnet overlaps an excluded Docker/host/reviewer network")
    peers = [ipaddress.IPv4Address(value) for value in reviewers]
    if (
        not peers
        or len(set(peers)) != len(peers)
        or any(
            peer not in network
            or peer in {server.ip, network.network_address, network.broadcast_address}
            for peer in peers
        )
    ):
        raise ValueError("Each reviewer needs a distinct usable peer address in the VPN subnet")
    if (
        type(udp_port) is not int
        or type(api_port) is not int
        or not 1024 <= udp_port <= 65535
        or not 1024 <= api_port <= 65535
    ):
        raise ValueError("Reviewed UDP and API ports must be integers from1024 through65535")
    files = {}
    server_config = (
        f"# OWNER MUST SUPPLY REAL KEYS PRIVATELY BEFORE INSTALL\n[Interface]\n"
        f"Address = {server}\nListenPort = {udp_port}\n"
        "PrivateKey = SET_SERVER_PRIVATE_KEY\n"
    )
    for number, peer in enumerate(peers, 1):
        server_config += (
            f"\n[Peer]\nPublicKey = SET_REVIEWER_{number:02}_PUBLIC_KEY\nAllowedIPs = {peer}/32\n"
        )
        files[f"reviewer-{number:02}.conf.example"] = (
            "# Fill on the recipient device; never share its private key.\n[Interface]\n"
            f"Address = {peer}/32\nPrivateKey = SET_THIS_DEVICE_PRIVATE_KEY\n\n[Peer]\n"
            f"PublicKey = SET_SERVER_PUBLIC_KEY\nEndpoint = SET_VPS_IP:{udp_port}\n"
            f"AllowedIPs = {server.ip}/32\nPersistentKeepalive = 25\n"
        )
    files[f"{INTERFACE}.conf.example"] = server_config
    addresses = ", ".join(str(peer) for peer in peers)
    allow_api = (
        f'iifname "{INTERFACE}" ip saddr {{ {addresses} }} '
        f"ip daddr {server.ip} tcp dport {api_port} accept"
    )
    # ExecStartPre creates our table if absent. Delete+replace in one nft transaction
    # avoids stale peer rules on reload and never flushes the host's global ruleset.
    files["reviewer-guard.nft"] = f"""delete table inet zoclip_reviewer_vpn
table inet zoclip_reviewer_vpn {{
  chain input {{
    type filter hook input priority -10; policy accept;
    {allow_api}
    iifname "{INTERFACE}" drop
    ip daddr {server.ip} tcp dport {api_port} iifname != "{INTERFACE}" drop
  }}
  chain forward {{
    type filter hook forward priority -10; policy accept;
    iifname "{INTERFACE}" drop
    oifname "{INTERFACE}" drop
  }}
}}
"""
    files["zoclip-reviewer-firewall.service"] = f"""[Unit]
Description=ZoClip reviewer VPN isolation (no global ruleset flush)
Before=wg-quick@{INTERFACE}.service zoclip-vpn-api.socket
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/usr/sbin/nft add table inet zoclip_reviewer_vpn
ExecStartPre=/usr/sbin/nft --check --file /etc/zoclip/wireguard/reviewer-guard.nft
ExecStart=/usr/sbin/nft --file /etc/zoclip/wireguard/reviewer-guard.nft
ExecReload=/usr/sbin/nft --file /etc/zoclip/wireguard/reviewer-guard.nft
# Stop intentionally retains filtering; no fail-open cleanup.
UMask=0077
"""
    files["wg-quick-firewall.conf"] = """[Unit]
Requires=zoclip-reviewer-firewall.service
After=zoclip-reviewer-firewall.service
"""
    files["zoclip-vpn-api.socket"] = f"""[Unit]
Description=ZoClip API on WireGuard only
DefaultDependencies=no
Conflicts=shutdown.target
Before=shutdown.target
Requires=sysinit.target wg-quick@{INTERFACE}.service
Requires=zoclip-reviewer-firewall.service zoclip-private.service
After=sysinit.target wg-quick@{INTERFACE}.service
After=zoclip-reviewer-firewall.service zoclip-private.service
BindsTo=wg-quick@{INTERFACE}.service zoclip-reviewer-firewall.service
[Socket]
ListenStream={server.ip}:{api_port}
BindToDevice={INTERFACE}
FreeBind=no
Accept=no
[Install]
WantedBy=multi-user.target
"""
    forward_command = (
        "ExecStart=/usr/lib/systemd/systemd-socket-proxyd --connections-max=32 "
        f"--exit-idle-time=5min 127.0.0.1:{api_port}"
    )
    files["zoclip-vpn-api.service"] = f"""[Unit]
Description=ZoClip encrypted TCP forward to existing loopback HTTPS
Requires=zoclip-vpn-api.socket
After=zoclip-vpn-api.socket
BindsTo=zoclip-vpn-api.socket
[Service]
Type=notify
{forward_command}
DynamicUser=yes
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_UNIX
MemoryMax=64M
TasksMax=16
LimitNOFILE=256
UMask=0077
"""
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-cidr", required=True)
    parser.add_argument("--reviewer-address", action="append", required=True)
    parser.add_argument("--exclude-cidr", action="append", default=[])
    parser.add_argument("--udp-port", type=int, default=51820)
    parser.add_argument("--api-port", type=int, default=8443)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    files = render_bundle(
        args.server_cidr, args.reviewer_address, args.udp_port, args.api_port, args.exclude_cidr
    )
    # These files contain placeholders only; actual keys are generated on approved devices.
    # Windows' special mkdir0700 ACL can exclude the sandbox identity; inherit workspace ACLs.
    args.output_dir.mkdir(mode=0o700 if os.name == "posix" else 0o755, parents=True, exist_ok=False)
    hashes = {}
    for name, content in files.items():
        with (args.output_dir / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        hashes[name] = hashlib.sha256(content.encode()).hexdigest()
    with (args.output_dir / "bundle.json").open("x", encoding="utf-8") as stream:
        json.dump({"state": "templates_only_not_installed", "sha256": hashes}, stream, indent=2)
    print(json.dumps({"state": "templates_only_not_installed", "files": sorted(files)}))


if __name__ == "__main__":
    main()
