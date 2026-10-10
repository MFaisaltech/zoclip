"""Exact-host HTTPS importer; resolve once, pin TLS socket, check every redirect."""

import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Callable
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

from zoclip.core.errors import ApiError
from zoclip.media.probe import magic_ok


def safe_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (
        address.is_global
        and not address.is_multicast
        and not getattr(address, "ipv4_mapped", None)
        and not getattr(address, "sixtofour", None)
        and not getattr(address, "teredo", None)
    )


def validate_url(url: str, hosts: list[str]) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (
            len(url) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
            or "\\" in url
            or parsed.scheme != "https"
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or host not in hosts
            or host
            in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "youtu.be",
                "vimeo.com",
                "www.vimeo.com",
            }
        ):
            raise ValueError("source")
        return host, (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    except (ValueError, UnicodeError) as exc:
        raise ApiError(
            422,
            "unsupported_source",
            "Only authorized direct HTTPS media on configured hosts is supported.",
        ) from exc


def resolve(host: str) -> list[str]:
    try:
        raw = subprocess.run(
            [sys.executable, "-m", "zoclip.media.resolve_host", host],
            capture_output=True,
            timeout=5,
            check=True,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("DNS deadline") from exc
    except subprocess.CalledProcessError as exc:
        raise OSError("DNS unavailable") from exc
    addresses = json.loads(raw.stdout)
    if not addresses or any(not safe_address(ip) for ip in addresses):
        raise ApiError(422, "unsafe_source", "Source network destination is forbidden.")
    return list(addresses)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, timeout: float):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=timeout, context=self.tls_context)
        self.validated_ip = ip

    def connect(self) -> None:
        # Numeric address: no second DNS lookup; hostname remains TLS SNI/cert identity.
        family = socket.AF_INET6 if ":" in self.validated_ip else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((self.validated_ip, 443))
            peer = sock.getpeername()[0]
            if ipaddress.ip_address(peer) != ipaddress.ip_address(
                self.validated_ip
            ) or not safe_address(peer):
                raise ApiError(422, "unsafe_source", "Source connection is forbidden.")
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def download(
    url: str,
    hosts: list[str],
    output: BinaryIO,
    max_bytes: int,
    *,
    connect: Callable = PinnedHTTPS,
    resolver: Callable = resolve,
    timeout: int = 120,
    progress: Callable[[], None] | None = None,
) -> int:
    deadline = time.monotonic() + timeout
    for redirect in range(4):
        host, target = validate_url(url, hosts)
        addresses = resolver(host)
        if not addresses or any(not safe_address(ip) for ip in addresses):
            raise ApiError(422, "unsafe_source", "Source network destination is forbidden.")
        connection = connect(host, addresses[0], min(10, max(0.1, deadline - time.monotonic())))
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "video/mp4,video/webm",
                    "Accept-Encoding": "identity",
                    "User-Agent": "ZoClip-authorized-import/1",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect == 3:
                    raise ApiError(422, "unsupported_source", "Source redirect limit exceeded.")
                url = urljoin(url, location)
                continue
            if (
                response.status != 200
                or (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
                not in {"video/mp4", "video/webm"}
                or response.getheader("Content-Encoding", "identity") != "identity"
            ):
                raise ApiError(422, "invalid_media", "Source must return direct MP4/WebM video.")
            length = response.getheader("Content-Length")
            if length and (not length.isdecimal() or int(length) > max_bytes):
                raise ApiError(413, "media_too_large", "Source exceeds admitted size.")
            size, prefix = 0, b""
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("import deadline")
                if connection.sock:
                    connection.sock.settimeout(min(10, remaining))
                chunk = response.read1(min(65536, max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(413, "media_too_large", "Source exceeds admitted size.")
                prefix = (prefix + chunk)[:32]
                output.write(chunk)
                if progress:
                    progress()
            if not magic_ok(prefix) or (length and size != int(length)):
                raise ApiError(422, "invalid_media", "Invalid or truncated source media.")
            return size
        finally:
            connection.close()
    raise ApiError(422, "unsupported_source", "Source redirect limit exceeded.")
