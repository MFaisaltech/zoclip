"""Generate bounded SYNTHETIC motion/speech fixtures, never real-workload evidence.

Supply locally synthesized speech WAV. A 30-second 1080p motion seed and the
speech seed are repeated; this intentionally measures infrastructure, not content
diversity or highlight quality. Existing outputs are never overwritten.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from decimal import Decimal
from pathlib import Path


def generate(audio: Path, output: Path, ffmpeg: str, ffprobe: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    # 2.5Mbps H264 +96kbps AAC, all three lengths plus 30s seed, and 4GiB cushion.
    estimated = 2_700_000 * (300 + 1800 + 7200 + 30) // 8
    free = shutil.disk_usage(output).free
    if free < estimated + 4 * 1024**3:
        raise RuntimeError("Insufficient workspace disk for bounded fixture generation")
    if not audio.is_file():
        raise ValueError("Locally generated speech WAV required")
    seed = output / "synthetic-motion-30s.mp4"
    targets = [output / f"synthetic-{m}min.mp4" for m in (5, 30, 120)]
    if any(p.exists() for p in [seed, *targets]):
        raise ValueError("Use a fresh output directory; existing fixtures are preserved")
    base = [ffmpeg, "-nostdin", "-v", "error", "-n"]
    started = time.monotonic()
    subprocess.run(
        base
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1920x1080:rate=30",
            "-t",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            "2500k",
            "-minrate",
            "2500k",
            "-maxrate",
            "2500k",
            "-bufsize",
            "5000k",
            "-x264-params",
            "nal-hrd=cbr:force-cfr=1",
            "-g",
            "60",
            "-an",
            str(seed),
        ],
        check=True,
        timeout=180,
    )
    rows = []
    for minutes, target in zip((5, 30, 120), targets, strict=True):
        if minutes == 5:
            media_args = [
                "-stream_loop",
                "-1",
                "-i",
                str(seed),
                "-stream_loop",
                "-1",
                "-i",
                str(audio),
                "-t",
                "300",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-threads",
                "2",
            ]
        else:
            # Repeat already encoded speech/video; do not re-encode hours of AAC.
            media_args = [
                "-stream_loop",
                "-1",
                "-i",
                str(targets[0]),
                "-t",
                str(minutes * 60 - 0.1),
                "-c",
                "copy",
            ]
        subprocess.run(
            base + media_args + ["-movflags", "+faststart", str(target)], check=True, timeout=300
        )
        metadata = json.loads(
            subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,size,bit_rate:stream=codec_name,width,height",
                    "-of",
                    "json",
                    str(target),
                ]
            )
        )
        duration = Decimal(metadata["format"]["duration"])
        nominal = Decimal(minutes * 60)
        if not nominal - Decimal("0.2") <= duration <= nominal:
            raise RuntimeError("Fixture does not fit the unchanged nominal source-duration cap")
        with target.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        rows.append(
            {
                "minutes": minutes,
                "file": target.name,
                "sha256": digest,
                "bytes": target.stat().st_size,
                "probe": metadata,
            }
        )
        print(
            json.dumps({"generated_minutes": minutes, "bytes": target.stat().st_size}), flush=True
        )
    result = {
        "synthetic": True,
        "video_seed_seconds": 30,
        "audio": "local offline speech seed",
        "video": "repeated FFmpeg testsrc2 motion pattern, not natural footage",
        "free_bytes_before": free,
        "generation_seconds": time.monotonic() - started,
        "files": rows,
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("speech_wav", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--allow-local-benchmark", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_benchmark:
        parser.error("Explicit synthetic CPU/disk generation opt-in required")
    generate(args.speech_wav, args.output, args.ffmpeg, args.ffprobe)
