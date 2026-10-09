"""Bound confirmed Telegram retry attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0008_delivery_attempts"
down_revision = "0007_knowledge_review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outbox", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("outbox", "attempts")
