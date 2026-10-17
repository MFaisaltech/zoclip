"""Pure template/validation checks. No WireGuard keys, network, firewall or systemd execution."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "prepare_wireguard", Path("deploy/prepare_wireguard.py")
)
vpn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpn)


@pytest.mark.parametrize(
    "server,peers",
    [
        ("0.0.0.0/24", ["0.0.0.1"]),
        ("8.8.8.1/24", ["8.8.8.2"]),
        ("127.0.0.1/24", ["127.0.0.2"]),
        ("192.0.2.1/24", ["192.0.2.2"]),
        ("10.88.13.1/8", ["10.88.13.2"]),
        ("10.88.13.1/32", ["10.88.13.2"]),
        ("10.88.13.0/24", ["10.88.13.2"]),
        ("10.88.13.255/24", ["10.88.13.2"]),
        ("10.88.13.1/24", []),
        ("10.88.13.1/24", ["10.88.13.1"]),
        ("10.88.13.1/24", ["10.88.14.2"]),
        ("10.88.13.1/24", ["10.88.13.0"]),
        ("10.88.13.1/24", ["10.88.13.255"]),
        ("10.88.13.1/24", ["10.88.13.2", "10.88.13.2"]),
        ("172.30.70.1/24", ["172.30.70.2"]),
        ("fd00::1/64", ["fd00::2"]),
        ("10.88.13.1/24\nPostUp=unsafe", ["10.88.13.2"]),
    ],
)
def test_reject_unsafe_address_scope(server, peers):
    with pytest.raises(ValueError):
        vpn.render_bundle(server, peers)


@pytest.mark.parametrize("port", [0, 443, 65536, True, "8443; unsafe"])
def test_reject_unsafe_ports(port):
    with pytest.raises(ValueError):
        vpn.render_bundle("10.88.13.1/24", ["10.88.13.2"], api_port=port)


def test_reject_owner_reported_route_overlap():
    with pytest.raises(ValueError, match="overlaps"):
        vpn.render_bundle("10.88.13.1/24", ["10.88.13.2"], exclude_cidrs=["10.88.0.0/16"])


def test_peer_routes_do_not_grant_host_or_docker_network_access():
    files = vpn.render_bundle("10.88.13.1/24", ["10.88.13.2", "10.88.13.3"])
    server = files["wg-zoclip.conf.example"]
    assert "AllowedIPs = 10.88.13.2/32" in server
    assert "AllowedIPs = 10.88.13.3/32" in server
    assert "AllowedIPs = 10.88.13.1/32" in files["reviewer-01.conf.example"]
    assert "Address = 10.88.13.2/32" in files["reviewer-01.conf.example"]
    assert "Address = 10.88.13.3/32" in files["reviewer-02.conf.example"]
    combined = "\n".join(files.values())
    for forbidden in ["0.0.0.0/0", "::/0", "PostUp", "MASQUERADE", "SaveConfig", "flush ruleset"]:
        assert forbidden not in combined


def test_socket_and_firewall_require_vpn_and_preserve_tls_loopback_destination():
    files = vpn.render_bundle("10.88.13.1/24", ["10.88.13.2"], api_port=18443)
    socket = files["zoclip-vpn-api.socket"]
    assert "ListenStream=10.88.13.1:18443" in socket
    assert "DefaultDependencies=no" in socket  # Late socket must not precede basic.target.
    assert "Conflicts=shutdown.target\nBefore=shutdown.target" in socket
    assert "BindToDevice=wg-zoclip\nFreeBind=no" in socket
    assert "BindsTo=wg-quick@wg-zoclip.service zoclip-reviewer-firewall.service" in socket
    assert "127.0.0.1:18443" in files["zoclip-vpn-api.service"]
    assert "--connections-max=32" in files["zoclip-vpn-api.service"]
    guard = files["reviewer-guard.nft"]
    assert "ip saddr { 10.88.13.2 } ip daddr 10.88.13.1 tcp dport 18443 accept" in guard
    assert guard.index("tcp dport 18443 accept") < guard.index('iifname "wg-zoclip" drop')
    assert "type filter hook forward priority -10" in guard
    assert 'oifname "wg-zoclip" drop' in guard
    assert 'iifname != "wg-zoclip" drop' in guard
    assert guard.startswith("delete table inet zoclip_reviewer_vpn\n")
    service = files["zoclip-reviewer-firewall.service"]
    assert "nft add table inet zoclip_reviewer_vpn" in service
    assert "--check --file" in service and "ExecStop=" not in service
    assert "Requires=zoclip-reviewer-firewall.service" in files["wg-quick-firewall.conf"]
