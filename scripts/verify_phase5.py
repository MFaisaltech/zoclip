"""Complete local Phase 1–5 gate; fixtures/mocks only, no live provider opt-in."""

import os
from pathlib import Path

import verify_phase3

if __name__ == "__main__":
    for key in list(os.environ):
        if key.startswith(("AI_", "DEEPGRAM_", "GEMINI_", "RENDER_")):
            os.environ.pop(key)
    os.environ["ZOCLIP_VERIFICATION_OUTPUT"] = str(Path.cwd() / "var/phase5-verification")
    verify_phase3.main()
