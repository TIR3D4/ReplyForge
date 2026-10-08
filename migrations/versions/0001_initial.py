"""Initial ReplyForge database schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "business_connections",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("can_reply", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "incoming_events",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_event_queue", "incoming_events", ["status", "available_at"])
    op.create_table(
        "knowledge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "subscription_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_hmac", sa.String(length=64), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("user_ref", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("customer_chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_connection_id", sa.String(length=255),
                  sa.ForeignKey("business_connections.id"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.String(length=24), nullable=False),
        sa.Column("workflow", sa.String(length=100), nullable=True),
        sa.Column("step", sa.String(length=100), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("menu_message_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_connection_id", "chat_id", name="uq_business_chat"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "telegram_message_id", "direction",
                            name="uq_conversation_message"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("buttons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_outbox_queue", "outbox", ["status", "available_at"])
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_tickets_status", "tickets", ["status", "created_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("actor", sa.String(length=30), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("audit_events")
    op.drop_index("idx_tickets_status", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("idx_outbox_queue", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("subscription_bindings")
    op.drop_table("knowledge")
    op.drop_index("idx_event_queue", table_name="incoming_events")
    op.drop_table("incoming_events")
    op.drop_table("business_connections")
