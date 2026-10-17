"""Add encrypted transactional mail queue; existing rows and balances are untouched."""

from alembic import op

revision = "d62f0c1b9a83"
down_revision = "c910a2e31f40"
branch_labels = None
depends_on = None


def upgrade():
    from zoclip.auth.mail_models import MailDelivery

    MailDelivery.__table__.create(op.get_bind())


def downgrade():
    op.drop_table("mail_deliveries")
