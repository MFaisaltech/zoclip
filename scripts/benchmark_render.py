"""Opt-in local long-source benchmark; no provider calls, prices or capacity claims."""

import argparse
import json
import resource
import time
from pathlib import Path

from zoclip.core.config import Settings
from zoclip.media.probe import probe
from zoclip.rendering.engine import render
from zoclip.rendering.schemas import Preferences


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--minutes", type=int, choices=[10, 30, 60, 120], required=True)
    parser.add_argument("--allow-local-benchmark", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_benchmark:
        parser.error("Explicit --allow-local-benchmark required; this consumes CPU and disk")
    settings = Settings()  # type: ignore[call-arg]
    metadata = probe(args.source, settings.ffprobe_binary)
    if abs(metadata["duration_seconds"] - args.minutes * 60) > 2:
        parser.error("Use a representative source matching --minutes")
    if args.output.exists():
        parser.error("Output must not already exist")
    started = time.monotonic()
    # Selected intervals near start/middle/end exercise long-GOP seek, not whole-source encoding.
    results = []
    for index, start in enumerate([0, args.minutes * 30000, args.minutes * 60000 - 20000]):
        target = args.output.with_name(args.output.stem + f"-{index}.mp4")
        if target.exists():
            parser.error("Benchmark target already exists")
        result = render(
            args.source.resolve(),
            target.resolve(),
            Preferences(start_ms=start, end_ms=start + 15000),
            [],
            settings,
            lambda: None,
        )
        results.append(result)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    print(
        json.dumps(
            {
                "source_minutes": args.minutes,
                "wall_seconds": time.monotonic() - started,
                "cpu_seconds": usage.ru_utime + usage.ru_stime,
                "peak_child_rss_kib": usage.ru_maxrss,
                "output_bytes": sum(r["size_bytes"] for r in results),
                "outputs": results,
                "queue_wait": "not measured (direct engine)",
                "provider_cost": "not measured; no provider calls",
                "pipeline_upload_transcription_analysis": "measure separately",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
