"""Generate schema from actual routes without connecting to external services."""

import json
from pathlib import Path

from zoclip.core.config import Settings
from zoclip.main import create_app

settings = Settings(
    _env_file=None, app_env="test", database_url="postgresql+psycopg://schema@localhost/schema"
)
app = create_app(settings)
schema = app.openapi()
Path("docs/openapi.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
