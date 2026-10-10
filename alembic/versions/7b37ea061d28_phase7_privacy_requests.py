"""Phase 7 durable audited erasure intent; all financial history remains intact."""

import sqlalchemy as sa

from alembic import op

revision = "7b37ea061d28"
down_revision = "651ba28dacf9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "privacy_erasure_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_erasure_requests")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_privacy_erasure_requests_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_privacy_erasure_requests_actor_id_users")
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_privacy_erasure_requests_user_id")),
    )
    op.create_index(
        op.f("ix_privacy_erasure_requests_actor_id"), "privacy_erasure_requests", ["actor_id"]
    )
    op.execute(
        "CREATE TRIGGER privacy_request_immutable BEFORE UPDATE OR DELETE OR TRUNCATE "
        "ON privacy_erasure_requests FOR EACH STATEMENT "
        "EXECUTE FUNCTION reject_financial_mutation()"
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM privacy_erasure_requests)")):
        raise RuntimeError("Refusing to erase privacy audit history; use a forward fix")
    op.drop_table("privacy_erasure_requests")
