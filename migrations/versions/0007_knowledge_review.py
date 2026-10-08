"""Reviewable FAQ candidates extracted from resolved support tickets.

Revision ID: 0007_knowledge_review
Revises: 0006_operator_drafts
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_knowledge_review"
down_revision = "0006_operator_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_knowledge_review", "knowledge_suggestions",
                    ["status", "created_at"])


def downgrade():
    op.drop_index("idx_knowledge_review", table_name="knowledge_suggestions")
    op.drop_table("knowledge_suggestions")
