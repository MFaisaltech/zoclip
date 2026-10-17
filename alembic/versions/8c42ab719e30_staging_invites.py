"""Single-use private-staging authorization; existing history and finance untouched."""

import sqlalchemy as sa

from alembic import op

revision = "8c42ab719e30"
down_revision = "7b37ea061d28"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staging_account_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("approval_hash", sa.String(64), nullable=False),
        sa.Column("target_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("purpose IN ('first_admin', 'reviewer')", name="purpose"),
        sa.CheckConstraint("consumed_at IS NULL OR revoked_at IS NULL", name="one_terminal_state"),
    )
    op.create_index("ix_staging_account_invites_user_id", "staging_account_invites", ["user_id"])
    op.create_index("ix_staging_account_invites_actor_id", "staging_account_invites", ["actor_id"])
    op.execute("""
        CREATE FUNCTION protect_staging_invite() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.id,NEW.created_at,NEW.user_id,NEW.actor_id,NEW.purpose,NEW.token_hash,
                 NEW.approval_hash,NEW.target_hash,NEW.expires_at)
             IS DISTINCT FROM
             ROW(OLD.id,OLD.created_at,OLD.user_id,OLD.actor_id,OLD.purpose,OLD.token_hash,
                 OLD.approval_hash,OLD.target_hash,OLD.expires_at)
             OR OLD.consumed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL
             OR (NEW.consumed_at IS NULL AND NEW.revoked_at IS NULL) THEN
            RAISE EXCEPTION 'Immutable staging invite or terminal state';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER staging_invite_transition BEFORE UPDATE ON staging_account_invites
          FOR EACH ROW EXECUTE FUNCTION protect_staging_invite();
        CREATE TRIGGER staging_invite_history BEFORE DELETE OR TRUNCATE ON staging_account_invites
          FOR EACH STATEMENT EXECUTE FUNCTION reject_financial_mutation();
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM staging_account_invites)")):
        raise RuntimeError("Refusing to erase staging authorization history; use a forward fix")
    op.drop_table("staging_account_invites")
    op.execute("DROP FUNCTION protect_staging_invite()")
