"""Selected-interval encode, cancellation, resource bounds and output validation."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.media.probe import probe
from zoclip.rendering.captions import ass
from zoclip.rendering.schemas import Preferences


def command(
    args: list[str],
    settings: Settings,
    cwd: Path,
    deadline: float,
    heartbeat: Callable[[], None],
    *,
    capture: bool = False,
) -> bytes:
    prefix = (
        []
        if sys.platform == "win32"
        else [
            sys.executable,
            "-m",
            "zoclip.rendering.runner",
            str(settings.render_deadline_seconds * 2 + 30),
            str(settings.render_max_bytes),
            str(os.getpid()),
        ]
    )
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            prefix + args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=output if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        try:
            while process.poll() is None:
                heartbeat()
                if time.monotonic() >= deadline:
                    raise TimeoutError("render deadline")
                time.sleep(0.1)
            if process.returncode:
                raise ApiError(422, "render_invalid", "Media subprocess failed validation.")
            output.seek(0)
            data = output.read(65537) if capture else b""
            if len(data) > 65536:
                raise ApiError(422, "render_invalid", "Subprocess metadata exceeded its bound.")
            return data
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def crop(prefs: Preferences, tracking: dict) -> str:
    if prefs.frame == "pad":
        return (
            "scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    focus = str(prefs.focal_x / 1000) if prefs.frame == "manual" else "0.5"
    if prefs.frame == "track" and tracking.get("samples"):
        samples = tracking["samples"]
        focus = f"{samples[-1][1]:.5f}"
        for (t0, x0), (t1, x1) in reversed(list(zip(samples, samples[1:], strict=False))):
            focus = (
                f"if(lt(t,{t1:.3f}),{x0:.5f}+({x1 - x0:.5f})*"
                f"max(0,t-{t0:.3f})/{max(0.001, t1 - t0):.3f},{focus})"
            )
    y = prefs.focal_y / 1000 if prefs.frame == "manual" else 0.5
    # Crop target aspect before scaling avoids unbounded upscaling of a very wide source.
    return (
        "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':"
        f"x='max(0,min(iw-ow,iw*({focus})-ow/2))':"
        f"y='max(0,min(ih-oh,ih*{y}-oh/2))',scale=720:1280,setsar=1"
    )


def validate_output(
    path: Path,
    prefs: Preferences,
    settings: Settings,
    deadline: float,
    heartbeat: Callable[[], None],
) -> dict:
    metadata = probe(path, settings.ffprobe_binary)
    expected = prefs.end_ms - prefs.start_ms
    if (
        metadata["width"],
        metadata["height"],
        metadata["video_codec"],
        metadata["audio_codecs"],
    ) != (720, 1280, "h264", ["aac"]):
        raise ApiError(422, "render_invalid", "Unexpected export codecs or dimensions.")
    if abs(metadata["duration_ms"] - expected) > 100:
        raise ApiError(422, "render_invalid", "Unexpected export duration.")
    raw = command(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "stream=codec_type,start_time,duration",
            "-of",
            "json",
            str(path),
        ],
        settings,
        path.parent,
        deadline,
        heartbeat,
        capture=True,
    )
    streams = json.loads(raw)["streams"]
    starts = [float(s["start_time"]) for s in streams]
    durations = [float(s["duration"]) for s in streams]
    if max(abs(s) for s in starts) > 0.1 or max(durations) - min(durations) > 0.1:
        raise ApiError(422, "render_invalid", "Export audio/video timing mismatch.")
    # Decode the entire short output; packet headers alone cannot prove a playable deliverable.
    command(
        [
            settings.ffmpeg_binary,
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-threads",
            "2",
            "-protocol_whitelist",
            "file",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-threads",
            "2",
            "-f",
            "null",
            "-",
        ],
        settings,
        path.parent,
        deadline,
        heartbeat,
    )
    size = path.stat().st_size
    if not 0 < size <= settings.render_max_bytes:
        raise ApiError(422, "render_invalid", "Export size exceeded its bound.")
    with path.open("rb") as output:
        digest = hashlib.file_digest(output, "sha256").hexdigest()
    return {**metadata, "sha256": digest, "size_bytes": size}


def render(
    source: Path,
    destination: Path,
    prefs: Preferences,
    transcript: list[dict],
    settings: Settings,
    heartbeat: Callable[[], None],
) -> dict:
    deadline = time.monotonic() + settings.render_deadline_seconds
    tracking: dict = {"mode": prefs.frame, "samples": []}
    with tempfile.TemporaryDirectory(prefix="render-", dir=destination.parent) as work:
        root = Path(work)
        if prefs.frame == "track":
            try:
                raw = command(
                    [
                        sys.executable,
                        "-m",
                        "zoclip.rendering.tracking",
                        str(source),
                        str(prefs.start_ms / 1000),
                        str((prefs.end_ms - prefs.start_ms) / 1000),
                    ],
                    settings,
                    root,
                    min(deadline, time.monotonic() + 20),
                    heartbeat,
                    capture=True,
                )
                tracking = json.loads(raw)
            except (ApiError, TimeoutError, ValueError) as exc:
                if isinstance(exc, ApiError) and exc.code != "render_invalid":
                    raise
                # Cancellation and stale fencing must propagate.
                heartbeat()
                tracking = {"mode": "center_fallback", "samples": []}
        subtitle = root / "captions.ass"
        subtitle.write_text(ass(prefs, transcript), encoding="utf-8")
        filters = crop(prefs, tracking) + ",fps=fps=30:start_time=0,format=yuv420p"
        if prefs.captions:
            filters += ",ass=filename=captions.ass"
        command(
            [
                settings.ffmpeg_binary,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-threads",
                "2",
                "-filter_threads",
                "1",
                "-protocol_whitelist",
                "file",
                "-ss",
                f"{prefs.start_ms / 1000:.3f}",
                "-i",
                str(source),
                "-t",
                f"{(prefs.end_ms - prefs.start_ms) / 1000:.3f}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-map_metadata",
                "-1",
                "-sn",
                "-dn",
                "-vf",
                filters,
                "-af",
                "aresample=async=1:first_pts=0,apad=whole_dur="
                + f"{(prefs.end_ms - prefs.start_ms) / 1000:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-maxrate",
                "4M",
                "-bufsize",
                "8M",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(destination),
            ],
            settings,
            root,
            deadline,
            heartbeat,
        )
        with destination.open("rb+") as file:
            os.fsync(file.fileno())
        metadata = validate_output(destination, prefs, settings, deadline, heartbeat)
        return {
            **metadata,
            "framing": tracking["mode"],
            "tracking_samples": len(tracking["samples"]),
        }
