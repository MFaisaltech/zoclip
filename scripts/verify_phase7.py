"""Linux full regression gate; all providers disabled, no live API or payment traffic."""

import os
from pathlib import Path

import verify_phase3

if __name__ == "__main__":
    os.environ["TEST_DATABASE_URL"] = Path("/run/secrets/test_database_url").read_text().strip()
    for key in list(os.environ):
        if key.startswith(("AI_", "DEEPGRAM_", "GEMINI_", "RENDER_", "PAYMENT_")):
            os.environ.pop(key)
    os.environ["PAYMENT_PROVIDER"] = "disabled"
    # Offline reruns use the existing locked cache, avoiding network in acceptance.
    if os.environ.get("ZOCLIP_PHASE7_OFFLINE") == "1":
        os.environ["UV_OFFLINE"] = "true"
    else:
        os.environ["ZOCLIP_VERIFICATION_CACHE"] = "/tmp/verification-uv-cache"
    os.environ["ZOCLIP_VERIFICATION_OUTPUT"] = str(Path.cwd() / "var/phase7-verification")
    verify_phase3.main()
