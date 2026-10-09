"""Temporary, explicitly reviewed image payloads for Insight tasks."""
from alembic import op
import sqlalchemy as sa
revision = '0012_reviewed_media'
down_revision = '0011_release_runtime'
branch_labels = depends_on = None


def upgrade():
    # Also supports the short-lived development snapshot that included this
    # nullable field in 0011 before the installation candidate was finalized.
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('insight_tasks')}
    if 'image_data' not in columns:
        op.add_column('insight_tasks', sa.Column('image_data', sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column('insight_tasks', 'image_data')
