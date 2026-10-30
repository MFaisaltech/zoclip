"""Opt-in authorized media probe inside an isolated worker, without DB/API calls."""

import argparse
import json
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import yt_dlp
from yt_dlp.plugins import directories

from zoclip.core.config import Settings
from zoclip.media.link_import import download_youtube, youtube_video_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-url", required=True)
    args = parser.parse_args()
    youtube_video_id(args.authorized_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://unused@localhost/unused_test",
        link_proxy_url="socks5://127.0.0.1:40000",
        link_extractor_args="youtube:player_client=mweb;fetch_pot=always",
        media_max_bytes=512 * 1024**2,
        link_deadline_seconds=600,
    )
    assert socket.getaddrinfo("www.youtube.com", 443)
    print("worker DNS: PASS", flush=True)
    assert directories(), "yt-dlp plugin discovery is empty"
    from yt_dlp_plugins.extractor.getpot_bgutil import __version__

    print("PO-token plugin:", __version__, flush=True)
    with urllib.request.urlopen("http://127.0.0.1:4416/ping", timeout=10) as response:
        assert response.status == 200
        print("private token service: PASS", flush=True)
    with yt_dlp.YoutubeDL({"proxy": settings.link_proxy_url, "quiet": True}) as ydl:
        with ydl.urlopen("https://www.cloudflare.com/cdn-cgi/trace") as response:
            trace = response.read(16384).decode()
        assert "warp=on" in trace, "Worker traffic did not use WARP"
    print("worker WARP egress: PASS", flush=True)
    with tempfile.TemporaryDirectory(prefix="zoclip-youtube-") as work:
        dest = Path(work) / "source.mp4"
        size = download_youtube(args.authorized_url, dest, settings)
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(dest),
                ],
                timeout=30,
            )
        )
        assert any(stream["codec_type"] == "video" for stream in probe["streams"])
        print(
            json.dumps({"download": "PASS", "bytes": size, "seconds": probe["format"]["duration"]}),
            flush=True,
        )


if __name__ == "__main__":
    main()
