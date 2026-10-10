"""Controlled HTTPS fixture, isolated Docker verification only; never a product service.

prepare generates disposable keys under ignored var/. serve binds port 443 and
serves only the synthetic fixture, plus deliberate redirect/MIME/size failures.
The client trusts the fixture CA through SSL_CERT_FILE, with normal verification.
"""

import argparse
import io
import os
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "media.phase3.test"


def check_transport(fixture: Path) -> None:
    from zoclip.core.errors import ApiError
    from zoclip.media.importer import download

    expected = fixture.read_bytes()
    output = io.BytesIO()
    download(f"https://{HOST}/source.mp4", [HOST], output, len(expected))
    assert output.getvalue() == expected
    try:
        download(
            "https://wrong.phase3.test/source.mp4",
            ["wrong.phase3.test"],
            io.BytesIO(),
            len(expected),
        )
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError("Wrong TLS hostname was accepted")
    trusted = os.environ.pop("SSL_CERT_FILE")
    try:
        try:
            download(f"https://{HOST}/source.mp4", [HOST], io.BytesIO(), len(expected))
        except ssl.SSLCertVerificationError:
            pass
        else:
            raise AssertionError("Untrusted fixture CA was accepted")
    finally:
        os.environ["SSL_CERT_FILE"] = trusted
    for url, hosts in (
        (f"https://{HOST}/source.mp4", []),
        ("https://127.0.0.1/source.mp4", ["127.0.0.1"]),
    ):
        try:
            download(url, hosts, io.BytesIO(), len(expected))
        except ApiError as exc:
            assert exc.code in {"unsupported_source", "unsafe_source"}
        else:
            raise AssertionError("Forbidden source was accepted")
    print(
        "Actual HTTPS transport: trusted TLS PASS; "
        "wrong hostname/untrusted CA/allowlist/private IP rejected"
    )


def prepare(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    commands = [
        [
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-sha256",
            "-subj",
            "/CN=ZoClip disposable Phase 3 CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-keyout",
            "ca.key",
            "-out",
            "ca.pem",
        ],
        [
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            f"/CN={HOST}",
            "-keyout",
            "server.key",
            "-out",
            "server.csr",
        ],
        [
            "x509",
            "-req",
            "-in",
            "server.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            "server.pem",
            "-days",
            "2",
            "-sha256",
            "-extfile",
            "server.ext",
        ],
    ]
    (directory / "server.ext").write_text(
        f"subjectAltName=DNS:{HOST}\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
    )
    for command in commands:
        subprocess.run(
            ["openssl", *command],
            cwd=directory,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    for key in directory.glob("*.key"):
        os.chmod(key, 0o600)
    print("Disposable CA and hostname-valid TLS certificate prepared")


def serve(directory: Path, fixture: Path) -> None:
    data = fixture.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # type: ignore[no-untyped-def]
            if self.path in {"/redirect", "/private-redirect"}:
                self.send_response(302)
                self.send_header(
                    "Location",
                    "/source.mp4" if self.path == "/redirect" else "https://127.0.0.1/source.mp4",
                )
                self.end_headers()
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html" if self.path == "/wrong-mime" else "video/mp4"
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):  # type: ignore[no-untyped-def]
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(directory / "server.pem", directory / "server.key")
    with ThreadingHTTPServer(("0.0.0.0", 443), Handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "serve", "check"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/source.mp4"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.directory)
    elif args.mode == "check":
        check_transport(args.fixture)
    else:
        serve(args.directory, args.fixture)
