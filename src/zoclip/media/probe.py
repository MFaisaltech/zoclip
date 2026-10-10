import json
import subprocess
import sys
import tempfile
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

from zoclip.core.errors import ApiError


def magic_ok(data: bytes) -> bool:
    return (len(data) >= 12 and data[4:8] == b"ftyp") or data.startswith(b"\x1a\x45\xdf\xa3")


def probe(path: Path, executable: str = "ffprobe") -> dict:
    with path.open("rb") as source:
        if not magic_ok(source.read(32)):
            raise ApiError(422, "invalid_media", "Supported MP4 or WebM media required.")
    prefix = [] if sys.platform == "win32" else [sys.executable, "-m", "zoclip.media.probe_runner"]
    command = prefix + [
        executable,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "mov,matroska,webm",
        "-max_alloc",
        "67108864",
        "-threads",
        "1",
        "-read_intervals",
        "%+1",
        "-count_packets",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,codec_name,width,height,duration,nb_read_packets",
        "-of",
        "json",
        str(path),
    ]
    try:
        with tempfile.TemporaryFile() as output:
            subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=25,
                check=True,
                shell=False,
            )
            output.seek(0)
            raw = output.read(131073)
        if len(raw) > 131072:
            raise ValueError("metadata limit")
        data = json.loads(raw)
        streams = data["streams"]
        if not 2 <= len(streams) <= 8:
            raise ValueError("streams")
        video = [s for s in streams if s["codec_type"] == "video"]
        audio = [s for s in streams if s["codec_type"] == "audio"]
        if len(video) != 1 or not audio:
            raise ValueError("audio/video required")
        v = video[0]
        if v["codec_name"] not in {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}:
            raise ValueError("video codec")
        if not (
            1 <= v["width"] <= 3840
            and 1 <= v["height"] <= 3840
            and v["width"] * v["height"] <= 3840 * 2160
        ):
            raise ValueError("dimensions")
        if any(
            s["codec_name"] not in {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le"}
            for s in audio
        ):
            raise ValueError("audio codec")
        if any(int(s.get("nb_read_packets", 0)) <= 0 for s in [v, *audio]):
            raise ValueError("no playable packets")
        durations = [Decimal(data["format"]["duration"])]
        durations.extend(
            Decimal(s["duration"]) for s in streams if s.get("duration") not in {None, "N/A"}
        )
        duration = max(durations)
        if not duration.is_finite() or duration <= 0:
            raise ValueError("duration")
        if duration > 7200:
            raise ApiError(422, "duration_exceeded", "Input duration exceeds 120 minutes.")
        return {
            "duration_seconds": int(duration.to_integral_value(rounding=ROUND_CEILING)),
            "width": v["width"],
            "height": v["height"],
            "video_codec": v["codec_name"],
            "audio_codecs": [s["codec_name"] for s in audio],
        }
    except FileNotFoundError as exc:
        raise ApiError(503, "probe_unavailable", "Media validator unavailable.") from exc
    except (ValueError, KeyError, TypeError, InvalidOperation, subprocess.SubprocessError) as exc:
        raise ApiError(422, "invalid_media", "Media validation failed.") from exc
