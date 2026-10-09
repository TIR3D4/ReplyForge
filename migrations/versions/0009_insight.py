"""Isolated, locally redacted historical analysis and approval queue."""
from alembic import op
import sqlalchemy as sa

revision = '0009_insight'
down_revision = '0008_delivery_attempts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('insight_imports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fingerprint', sa.String(64), unique=True, nullable=False),
        sa.Column('statistics', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('insight_candidates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('import_id', sa.Integer(), sa.ForeignKey('insight_imports.id'), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('question', sa.String(500), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('media_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)))
    op.create_index('ix_insight_candidates_import_id', 'insight_candidates', ['import_id'])


def downgrade():
    op.drop_table('insight_candidates')
    op.drop_table('insight_imports')
