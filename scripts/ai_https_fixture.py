"""Isolated provider simulator ONLY. No product adapter/config can enable this server."""

import argparse
import json
import os
import ssl
import subprocess
import tempfile
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOSTS = "DNS:api.deepgram.com,DNS:generativelanguage.googleapis.com,DNS:media.phase3.test"


def prepare(directory: Path) -> None:
    from https_fixture import prepare as prepare_ca

    prepare_ca(directory)
    (directory / "server.ext").write_text(
        f"subjectAltName={HOSTS}\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
    )
    subprocess.run(
        [
            "openssl",
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
        cwd=directory,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    if os.name == "posix":
        os.chown(directory, 10001, 10001)
        os.chown(directory / "server.key", 10001, 10001)
    print("Isolated provider TLS SANs prepared; no public interception or trust-store changes")


def serve(directory: Path, fixture: Path) -> None:
    if os.environ.get("ZOCLIP_PROVIDER_SIMULATOR") != "1":
        raise RuntimeError("Explicit isolated provider simulator opt-in required")
    media = fixture.read_bytes()

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
            self.send_header("Content-Length", str(len(media)))
            self.end_headers()
            self.wfile.write(media)

        def do_POST(self):  # type: ignore[no-untyped-def]
            host = self.headers.get("Host")
            expected = "synthetic-phase4-not-a-live-key"
            if host == "api.deepgram.com":
                assert self.headers.get("Authorization") == "Token " + expected
                assert self.path.startswith("/v1/listen?")
            else:
                assert host == "generativelanguage.googleapis.com"
                assert self.headers.get("x-goog-api-key") == expected
                assert self.path == "/v1beta/models/fictional-test:generateContent"
            with tempfile.TemporaryFile() as body:
                size = 0
                if self.headers.get("Transfer-Encoding") == "chunked":
                    while True:
                        length = int(self.rfile.readline(100).strip(), 16)
                        if length == 0:
                            self.rfile.readline(100)
                            break
                        size += length
                        assert size <= 240 * 1024**2
                        body.write(self.rfile.read(length))
                        assert self.rfile.read(2) == b"\r\n"
                else:
                    size = int(self.headers["Content-Length"])
                    assert 0 < size <= 100000
                    body.write(self.rfile.read(size))
                body.seek(0)
                if host == "api.deepgram.com":
                    with wave.open(body, "rb") as audio:
                        assert audio.getnchannels() == 1 and audio.getframerate() == 16000
                        duration = audio.getnframes() / audio.getframerate()
                        assert 2.4 <= duration <= 3
                    response = {
                        "metadata": {"duration": duration, "request_id": "local-simulator"},
                        "results": {
                            "channels": [
                                {
                                    "alternatives": [
                                        {
                                            "confidence": 0.9,
                                            "words": [
                                                {
                                                    "word": w,
                                                    "start": i * 0.5,
                                                    "end": (i + 1) * 0.5,
                                                    "confidence": 0.9,
                                                    "speaker": i % 2,
                                                }
                                                for i, w in enumerate(
                                                    ["Useful", "ideas", "help", "people", "learn."]
                                                )
                                            ],
                                        }
                                    ]
                                }
                            ]
                        },
                    }
                else:
                    request = json.load(body)
                    assert request["generationConfig"]["responseMimeType"] == "application/json"
                    response = {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {
                                    "parts": [
                                        {
                                            "text": json.dumps(
                                                {
                                                    "moments": [
                                                        {
                                                            "start_sec": 0,
                                                            "end_sec": 2.5,
                                                            "title": "Synthetic fixture insight",
                                                            "hook": "Useful ideas",
                                                            "reason": "Synthetic test",
                                                            "score": 80,
                                                            "keywords": ["fixture"],
                                                            "hashtags": ["#fixture"],
                                                        }
                                                    ]
                                                }
                                            )
                                        }
                                    ]
                                },
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 100,
                            "candidatesTokenCount": 50,
                            "thoughtsTokenCount": 0,
                            "totalTokenCount": 150,
                        },
                    }
            raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):  # type: ignore[no-untyped-def]
            pass  # No audio, transcript, credentials, headers or path logs.

    server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(directory / "server.pem", directory / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print("Isolated provider simulator ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "serve"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--fixture", type=Path, default=Path("/verify/source.mp4"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.directory)
    else:
        serve(args.directory, args.fixture)
