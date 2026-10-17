"""Run only the two documented read-only metadata GETs; no media or inference."""

import json
from pathlib import Path

from zoclip.core.config import Settings
from zoclip.ops.provider_metadata import verify

if __name__ == "__main__":
    try:
        evidence = Path("var/commercial-delivery-20261017/provider-evidence")
        result = verify(Settings(), evidence)  # type: ignore[call-arg]
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(
            0
            if len(result["providers"]) == 2
            and all(item["credential_accepted"] for item in result["providers"].values())
            else 1
        )
    except Exception as exc:
        print("STOP: metadata check " + type(exc).__name__ + "; no inference or automatic retry")
        raise SystemExit(1) from None
