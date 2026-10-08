"""Review-only AI suggestions.

Revision ID: 0006_operator_drafts
Revises: 0005_support_ops
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_operator_drafts"
down_revision = "0005_support_ops"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operator_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_drafts_conversation", "operator_drafts",
                    ["conversation_id", "status"])


def downgrade():
    op.drop_index("idx_drafts_conversation", table_name="operator_drafts")
    op.drop_table("operator_drafts")
