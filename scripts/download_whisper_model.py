"""Image-build only. Immutable public model revision; runtime must stay offline."""

import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

REVISION = "536b0662742c02347bc0e980a01041f333bce120"
FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def main():
    root = Path("/opt/models/faster-whisper-small")
    snapshot_download(
        "Systran/faster-whisper-small",
        revision=REVISION,
        allow_patterns=FILES,
        local_dir=root,
        token=False,
    )
    manifest = {
        "revision": REVISION,
        "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in FILES},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    # Root-owned, readable to unprivileged UID10001, immutable in read-only runtime.
    for item in root.rglob("*"):
        item.chmod(0o555 if item.is_dir() else 0o444)
    root.chmod(0o555)


if __name__ == "__main__":
    main()
