"""Versioned business playbooks.

Revision ID: 0002_playbook
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_playbook"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "playbook_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("playbook_versions")
