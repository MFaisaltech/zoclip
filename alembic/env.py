from alembic import context
from zoclip.ai import models as ai_models  # noqa: F401
from zoclip.auth import models  # noqa: F401
from zoclip.billing import models as billing_models  # noqa: F401
from zoclip.core.config import Settings
from zoclip.core.db import Base, build_engine
from zoclip.credits import models as credits_models  # noqa: F401
from zoclip.media import models as media_models  # noqa: F401
from zoclip.rendering import models as rendering_models  # noqa: F401

settings = Settings()
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    context.configure(
        connection=context.config.attributes["connection"],
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
