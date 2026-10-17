"""Read-only, offline preparation check. Never enables AI or connects to services."""

import json
import shutil
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import ArgumentError

from zoclip.core.config import Settings


def main() -> int:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        # Even validation errors may contain private input; print field names only.
        print(
            json.dumps(
                {
                    "configuration_valid": False,
                    "invalid_fields": [
                        ".".join(map(str, item["loc"]))
                        for item in error.errors(include_input=False)
                    ],
                }
            )
        )
        return 1
    except (ArgumentError, OSError, ValueError):
        # Invalid connection URLs / dotenv inputs must not produce a traceback.
        print(json.dumps({"configuration_valid": False, "invalid_fields": ["environment"]}))
        return 1
    if settings.ai_enabled:
        print(json.dumps({"configuration_valid": False, "error": "AI must remain disabled"}))
        return 1

    root = Path(settings.media_root).resolve()
    existing = root
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    source = 3 * settings.media_max_bytes + 2 * 1024**3
    output = 2 * settings.render_max_bytes
    required = settings.media_headroom_bytes + source + output
    missing = [
        name.upper()
        for name in ("deepgram_model", "deepgram_version", "gemini_model")
        if not getattr(settings, name)
    ]
    credentials = {
        name.upper(): bool(getattr(settings, name).get_secret_value())
        for name in ("deepgram_api_key", "gemini_api_key")
    }
    binaries = {
        name.upper(): bool(shutil.which(getattr(settings, name)))
        for name in ("ffmpeg_binary", "ffprobe_binary")
    }
    print(
        json.dumps(
            {
                "configuration_valid": True,
                "ai_enabled": False,
                "credentials_present": credentials,
                "missing_model_fields": missing,
                "moving_deepgram_version": settings.deepgram_version.lower() in {"latest", "beta"},
                "binaries_present": binaries,
                "free_bytes": free,
                "headroom_bytes": settings.media_headroom_bytes,
                "source_reservation_at_upload_cap_bytes": source,
                "one_output_reservation_bytes": output,
                "minimum_free_bytes_at_caps_without_other_reservations": required,
                "capacity_at_caps_without_other_reservations": free >= required,
                "shortfall_bytes_without_other_reservations": max(0, required - free),
                "database_rates_budgets_and_outstanding_reservations": "NOT CHECKED: offline only",
                "live_readiness": "BLOCKED: manual gates and explicit approval required",
            },
            indent=2,
        )
    )
    # Success means valid disabled preparation, never permission for live processing.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
