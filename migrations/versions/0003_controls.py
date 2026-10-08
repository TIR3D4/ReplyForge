"""Runtime automation controls.

Revision ID: 0003_controls
Revises: 0002_playbook
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_controls"
down_revision = "0002_playbook"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "controls",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("controls")
