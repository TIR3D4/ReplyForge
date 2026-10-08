"""Normalized secure subscription bearer fingerprints.

Revision ID: 0004_token_bindings
Revises: 0003_controls
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_token_bindings"
down_revision = "0003_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscription_bindings",
                  sa.Column("token_hmac", sa.String(length=64), nullable=True))
    op.create_index("ix_subscription_bindings_token_hmac", "subscription_bindings", ["token_hmac"])


def downgrade():
    op.drop_index("ix_subscription_bindings_token_hmac", table_name="subscription_bindings")
    op.drop_column("subscription_bindings", "token_hmac")
