"""Read-only current-source and live OpenAPI checks inside isolated API container."""

import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import zoclip
from zoclip.core.config import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.app_env != "development":
        raise RuntimeError("Isolated development container required")
    root = Path("/workspace")
    installed = Path(zoclip.__file__).parent
    expected = root / "src/zoclip"
    files = list(expected.rglob("*.py"))
    assert files
    hashes = {}
    for source in files:
        relative = source.relative_to(expected)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        assert hashlib.sha256((installed / relative).read_bytes()).hexdigest() == digest, relative
        hashes[str(relative)] = digest
    request = urllib.request.Request(
        "http://api:8000/openapi.json",
        headers={"Host": urlsplit(settings.api_public_url).netloc},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        schema = json.load(response)
    assert schema == json.loads((root / "docs/openapi.json").read_text())
    print(f"PASS: installed image matches all {len(files)} current Python sources")
    print(f"PASS: running API matches OpenAPI snapshot ({len(schema['paths'])} paths)")
    print(json.dumps({"source_sha256": hashes}, sort_keys=True))


if __name__ == "__main__":
    main()
