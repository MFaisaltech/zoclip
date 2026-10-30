"""Admin simplification: order customer_name, append-only credit-expiry events, EXPIRE ledger op.

Adds billing_orders.customer_name (the payer name recorded by staff during a
manual purchase), a credit_expiry_events table (the credit-expiry sweep's
append-only once-only processing record — user_entitlements itself is
immutable), and an EXPIRE arm in the wallet_transactions operation-deltas
check so the sweep can append expiry deductions.

Revision ID: f4a9c2b71e08
Revises: e7319c2b504a
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "f4a9c2b71e08"
down_revision = "e7319c2b504a"
branch_labels = None
depends_on = None

OLD_CHECK = (
    "(operation = 'GRANT' AND available_delta > 0 AND reserved_delta = 0) OR "
    "(operation = 'RESERVE' AND available_delta < 0 "
    "AND reserved_delta = -available_delta) OR "
    "(operation = 'SETTLE' AND available_delta = 0 AND reserved_delta < 0) OR "
    "(operation = 'RELEASE' AND available_delta > 0 "
    "AND reserved_delta = -available_delta) OR "
    "(operation IN ('REFUND', 'ADMIN_ADJUST') "
    "AND available_delta != 0 AND reserved_delta = 0)"
)
NEW_CHECK = OLD_CHECK + " OR (operation = 'EXPIRE' AND available_delta < 0 AND reserved_delta = 0)"


def upgrade() -> None:
    op.add_column("billing_orders", sa.Column("customer_name", sa.String(120), nullable=True))
    op.create_table(
        "credit_expiry_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entitlement_id", sa.Uuid(), nullable=False),
        sa.Column("deducted_credits", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "deducted_credits >= 0", name=op.f("ck_credit_expiry_events_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_id"],
            ["user_entitlements.id"],
            name=op.f("fk_credit_expiry_events_entitlement_id_user_entitlements"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credit_expiry_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_expiry_events")),
        sa.UniqueConstraint("entitlement_id", name=op.f("uq_credit_expiry_events_entitlement_id")),
    )
    op.create_index(
        op.f("ix_credit_expiry_events_user_id"), "credit_expiry_events", ["user_id"], unique=False
    )
    op.drop_constraint("operation_deltas", "wallet_transactions", type_="check")
    op.create_check_constraint("operation_deltas", "wallet_transactions", NEW_CHECK)


def downgrade() -> None:
    op.drop_constraint("operation_deltas", "wallet_transactions", type_="check")
    op.create_check_constraint("operation_deltas", "wallet_transactions", OLD_CHECK)
    op.drop_index(op.f("ix_credit_expiry_events_user_id"), table_name="credit_expiry_events")
    op.drop_table("credit_expiry_events")
    op.drop_column("billing_orders", "customer_name")
