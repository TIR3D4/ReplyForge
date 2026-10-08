"""Individual staff credentials and role separation."""
from alembic import op
import sqlalchemy as sa
revision = '0010_operators'
down_revision = '0009_insight'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('operators',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(80), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('operators')
