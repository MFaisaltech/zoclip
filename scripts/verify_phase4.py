"""Exact mounted-source Linux regression runner. No paid provider calls."""

import os
from pathlib import Path

import verify_phase3

if __name__ == "__main__":
    # Compose simulator configuration must not leak into isolated test settings.
    for key in list(os.environ):
        if key.startswith(("AI_", "DEEPGRAM_", "GEMINI_")):
            os.environ.pop(key)
    os.environ["ZOCLIP_VERIFICATION_OUTPUT"] = str(Path.cwd() / "var/phase4-verification")
    verify_phase3.main()
