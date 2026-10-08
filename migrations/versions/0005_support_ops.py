"""Operator queue, SLA and private ticket notes.

Revision ID: 0005_support_ops
Revises: 0004_token_bindings
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_support_ops"
down_revision = "0004_token_bindings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("category", sa.String(50), nullable=False,
                                       server_default="general"))
    op.add_column("tickets", sa.Column("priority", sa.String(12), nullable=False,
                                       server_default="normal"))
    op.add_column("tickets", sa.Column("assignee", sa.String(100), nullable=True))
    op.add_column("tickets", sa.Column("first_response_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("last_customer_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("sla_due_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("escalated_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("resolution_summary", sa.Text()))
    op.create_index("idx_tickets_sla", "tickets",
                    ["status", "first_response_at", "sla_due_at"])
    op.create_table(
        "ticket_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_ticket_notes", "ticket_notes", ["ticket_id", "created_at"])


def downgrade():
    op.drop_index("idx_ticket_notes", table_name="ticket_notes")
    op.drop_table("ticket_notes")
    op.drop_index("idx_tickets_sla", table_name="tickets")
    for column in (
        "resolution_summary", "resolved_at", "escalated_at", "sla_due_at",
        "last_customer_at", "first_response_at", "assignee",
        "priority", "category",
    ):
        op.drop_column("tickets", column)
