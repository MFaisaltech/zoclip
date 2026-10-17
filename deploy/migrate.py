"""One migrator owns schema; runtime may operate rows, never DDL or migration version."""

from alembic.config import Config
from sqlalchemy import text

from alembic import command
from zoclip.core.config import Settings
from zoclip.core.db import build_engine

command.upgrade(Config("alembic.ini"), "head")
settings = Settings()
engine = build_engine(settings.database_url.get_secret_value())
with engine.begin() as db:
    db.execute(text("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM zoclip_runtime"))
    db.execute(text("REVOKE DELETE, TRUNCATE ON staging_account_invites FROM zoclip_runtime"))
    # Default privileges survive future migrations; all append-only triggers stay active.
    for table in (
        "wallet_transactions",
        "credit_quotes",
        "plan_price_versions",
        "user_entitlements",
        "cost_rate_versions",
        "cost_policy_versions",
        "provider_usage",
        "admin_audit_logs",
        "job_events",
        "payment_attempts",
        "payment_events",
        "billing_refunds",
        "billing_entitlement_revocations",
        "billing_staff_actions",
        "privacy_erasure_requests",
    ):
        db.execute(text(f"REVOKE UPDATE, DELETE ON {table} FROM zoclip_runtime"))
engine.dispose()
