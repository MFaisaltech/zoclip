"""Allow local transcription receipts without pretending they are paid Deepgram calls.

Additive constraint widening only: no existing rows, rates or balances are changed.
"""

from sqlalchemy import text

from alembic import op

revision = "e7319c2b504a"
down_revision = "d62f0c1b9a83"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_ai_requests_provider"), "ai_requests", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_requests_provider"),
        "ai_requests",
        "provider IN ('deepgram','gemini','whisper')",
    )


def downgrade():
    if op.get_bind().scalar(
        text("SELECT EXISTS (SELECT 1 FROM ai_requests WHERE provider='whisper')")
    ):
        raise RuntimeError("Refusing to remove local transcription history")
    op.drop_constraint(op.f("ck_ai_requests_provider"), "ai_requests", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_requests_provider"), "ai_requests", "provider IN ('deepgram','gemini')"
    )
