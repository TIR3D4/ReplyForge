"""Independent usage ledger and resumable Insight refinement tasks."""
from alembic import op
import sqlalchemy as sa
revision = '0011_release_runtime'
down_revision = '0010_operators'
branch_labels = depends_on = None


def upgrade():
    op.create_table('login_buckets', sa.Column('key', sa.String(64), primary_key=True),
                    sa.Column('attempts', sa.Integer(), nullable=False),
                    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('ai_budget_days', sa.Column('day', sa.String(10), primary_key=True),
                    sa.Column('used_microusd', sa.BigInteger(), nullable=False))
    op.create_table('ai_usage', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('day', sa.String(10), nullable=False), sa.Column('scope', sa.String(80), nullable=False),
        sa.Column('model', sa.String(120), nullable=False),
        sa.Column('reserved_microusd', sa.BigInteger(), nullable=False),
        sa.Column('charged_microusd', sa.BigInteger(), nullable=False),
        sa.Column('input_tokens', sa.BigInteger()), sa.Column('output_tokens', sa.BigInteger()),
        sa.Column('input_price', sa.String(30), nullable=False), sa.Column('output_price', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_ai_usage_day', 'ai_usage', ['day'])
    op.create_index('ix_ai_usage_scope', 'ai_usage', ['scope'])
    op.create_table('insight_tasks', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('import_id', sa.Integer(), sa.ForeignKey('insight_imports.id'), nullable=False),
        sa.Column('candidate_id', sa.Integer(), sa.ForeignKey('insight_candidates.id'), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('image_data', sa.LargeBinary(), nullable=True), sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_insight_tasks_import_id', 'insight_tasks', ['import_id'])


def downgrade():
    op.drop_table("login_buckets")
    op.drop_table('insight_tasks')
    op.drop_table('ai_usage')
    op.drop_table('ai_budget_days')
