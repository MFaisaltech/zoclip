import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    if sys.argv[1:] == ["maintenance"]:
        age = time.time() - Path("/tmp/zoclip-maintenance-heartbeat").stat().st_mtime
        if not 0 <= age < 120:
            raise SystemExit(1)
    elif sys.argv[1:] == ["worker"]:
        from redis import Redis
        from rq import Worker

        from zoclip.core.config import Settings

        settings = Settings()  # type: ignore[call-arg]
        import os

        if os.environ.get("WORKER_QUEUE") == "ai" and settings.transcription_provider == "whisper":
            from zoclip.ai.providers import check_whisper_files

            check_whisper_files(settings)
            # Health must not call inference/download or fail merely because the
            # single work horse is CPU-busy. Check its declared resource envelope.
            memory_limit = Path("/sys/fs/cgroup/memory.max")
            if memory_limit.is_file():
                value = memory_limit.read_text().strip()
                if value != "max" and int(value) < 2 * 1024**3:
                    raise SystemExit(1)
        with Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=3) as redis:
            name = Path("/tmp/zoclip-rq-worker-name").read_text()
            workers = [w for w in Worker.all(connection=redis) if w.name == name]
            if len(workers) != 1 or workers[0].last_heartbeat is None:
                raise SystemExit(1)
            age = (datetime.now(UTC) - workers[0].last_heartbeat).total_seconds()
            if not 0 <= age < 480:
                raise SystemExit(1)
    else:
        raise SystemExit("Expected worker or maintenance")


if __name__ == "__main__":
    main()
