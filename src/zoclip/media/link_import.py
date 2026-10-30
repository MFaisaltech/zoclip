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


def is_youtube_host(url: str) -> bool:
    """Routing hint only; every YouTube URL is validated again before admission."""
    try:
        return (urlsplit(url).hostname or "").lower() in _YOUTUBE_HOSTS | {"youtu.be"}
    except ValueError:
        return False


def youtube_video_id(url: str) -> str:
    """Return the validated video id or raise 422 unsupported_source."""
    try:
        url = url.strip(" ")
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
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError("source")
        return video_id
    except (ValueError, UnicodeError) as exc:
        raise ApiError(
            422, "unsupported_source", "Only YouTube video links are supported."
        ) from exc


def canonical_youtube_url(url: str) -> str:
    # Never hand user-controlled queries, fragments or redirect targets to yt-dlp.
    return "https://www.youtube.com/watch?v=" + youtube_video_id(url)


def build_args(url: str, dest: Path, settings: Settings) -> list[str]:
    args = [
        settings.ytdlp_binary,
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--no-cache-dir",
        "--js-runtimes",
        "node",
        "--socket-timeout",
        "20",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
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
    args += ["--", canonical_youtube_url(url)]
    return args


def download_youtube(
    url: str,
    dest: Path,
    settings: Settings,
    progress: Callable[[], None] = lambda: None,
) -> int:
    """Download and merge the video to ``dest``; return its size in bytes."""
    youtube_video_id(url)  # revalidate: the worker never trusts the payload alone
    if settings.app_env == "production" and not settings.link_proxy_url:
        raise ApiError(503, "link_runtime_unavailable", "Video import is temporarily unavailable.")
    deadline = time.monotonic() + settings.link_deadline_seconds
    proc = subprocess.Popen(
        build_args(url, dest, settings),
        shell=False,
        # Progress is polled through the application heartbeat. Unread pipes can
        # fill and deadlock yt-dlp; provider diagnostics must not reach customers.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise TimeoutError("link download deadline")
            progress()
            time.sleep(2)
        proc.communicate()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if proc.returncode != 0:
        # yt-dlp errors may contain signed media URLs or proxy credentials.
        raise ApiError(422, "link_download_failed", "Video download failed. Please retry later.")
    if not dest.exists():
        raise ApiError(422, "link_download_failed", "Video download produced no file.")
    size = dest.stat().st_size
    if size == 0 or size > settings.media_max_bytes:
        raise ApiError(422, "link_download_failed", "Downloaded video has an invalid size.")
    return size
