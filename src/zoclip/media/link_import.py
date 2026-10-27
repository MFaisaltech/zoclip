"""YouTube link ingestion via yt-dlp (constrained subprocess).

Only canonical YouTube watch/shorts/live/embed and youtu.be URLs are
accepted; the video id is extracted and validated. Downloads are
argument-array subprocess calls (never a shell), size-capped by
yt-dlp's --max-filesize and re-checked on disk, with a hard deadline.
The proxy / PO-token extractor configuration exists because plain
datacenter egress is bot-challenged by YouTube; both are settings,
not code, so deployments choose their own egress.
"""

import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"


def youtube_video_id(url: str) -> str:
    """Return the validated video id or raise 422 unsupported_source."""
    try:
        if len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError("source")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (
            parsed.scheme != "https"
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("source")
        video_id = ""
        if host in _YOUTUBE_HOSTS:
            if parsed.path == "/watch":
                video_id = (parse_qs(parsed.query).get("v") or [""])[0]
            else:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
                    video_id = parts[1]
        elif host == "youtu.be":
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) == 1:
                video_id = parts[0]
        if not _VIDEO_ID.match(video_id):
            raise ValueError("source")
        return video_id
    except (ValueError, UnicodeError) as exc:
        raise ApiError(
            422, "unsupported_source", "Only YouTube video links are supported."
        ) from exc


def build_args(url: str, dest: Path, settings: Settings) -> list[str]:
    args = [
        settings.ytdlp_binary,
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "-f",
        _FORMAT,
        "--merge-output-format",
        "mp4",
        "--max-filesize",
        str(settings.media_max_bytes),
        "-o",
        str(dest),
    ]
    if settings.link_proxy_url:
        args += ["--proxy", settings.link_proxy_url]
    if settings.link_extractor_args:
        args += ["--extractor-args", settings.link_extractor_args]
    args += ["--", url]
    return args


def download_youtube(
    url: str,
    dest: Path,
    settings: Settings,
    progress: Callable[[], None] = lambda: None,
) -> int:
    """Download and merge the video to ``dest``; return its size in bytes."""
    youtube_video_id(url)  # revalidate: the worker never trusts the payload alone
    deadline = time.monotonic() + settings.link_deadline_seconds
    proc = subprocess.Popen(
        build_args(url, dest, settings),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise TimeoutError("link download deadline")
            progress()
            time.sleep(2)
        _out, err = proc.communicate()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if proc.returncode != 0:
        tail = (err or b"")[-300:].decode("utf-8", "replace").strip()
        raise ApiError(422, "link_download_failed", f"Video download failed. {tail}")
    if not dest.exists():
        raise ApiError(422, "link_download_failed", "Video download produced no file.")
    size = dest.stat().st_size
    if size == 0 or size > settings.media_max_bytes:
        raise ApiError(422, "link_download_failed", "Downloaded video has an invalid size.")
    return size
