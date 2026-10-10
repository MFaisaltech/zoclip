"""Linux Phase 1–6 gate, paid providers excluded and mock billing explicit in tests."""

import os
from pathlib import Path

import verify_phase3

if __name__ == "__main__":
    for key in list(os.environ):
        if key.startswith(("AI_", "DEEPGRAM_", "GEMINI_", "RENDER_", "PAYMENT_")):
            os.environ.pop(key)
    os.environ["PAYMENT_PROVIDER"] = "disabled"
    os.environ["ZOCLIP_VERIFICATION_OUTPUT"] = str(Path.cwd() / "var/phase6-verification")
    verify_phase3.main()
