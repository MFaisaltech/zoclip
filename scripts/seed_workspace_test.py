"""Append synthetic M2 fixtures ONLY to a new auth_dev.py browser test database."""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from zoclip.core.db import build_engine

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-disposable-local", action="store_true")
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state_path = args.state.resolve()
    if not args.allow_disposable_local or not state_path.is_relative_to(ROOT / "var/phase8-auth"):
        parser.error("Explicit disposable local state and opt-in required")
    if state_path.name != "state.json" or len(state_path.parent.name) != 32:
        parser.error("Expected an auth_dev.py run state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    url = make_url(state["database_url"])
    if (url.drivername, url.host, url.port, url.database) != (
        "postgresql+psycopg",
        "127.0.0.1",
        55438,
        "zoclip_phase8_browser_test",
    ):
        parser.error("Refusing a non-disposable database")
    manifest = state_path.with_name("workspace-fixture.json")
    if manifest.exists():
        parser.error("Fixtures already exist; existing data is preserved")
    sys.path.insert(0, str(ROOT / "tests"))
    from workspace_fixture import seed_workspace

    engine = build_engine(state["database_url"])
    try:
        fixture = seed_workspace(sessionmaker(engine, expire_on_commit=False))
        manifest.write_text(json.dumps(fixture), encoding="utf-8")
        manifest.chmod(0o600)
    finally:
        engine.dispose()
    print("Synthetic fixtures appended to disposable browser DB; private manifest saved.")


if __name__ == "__main__":
    main()
