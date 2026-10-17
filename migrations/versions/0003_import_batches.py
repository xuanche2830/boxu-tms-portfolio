"""Durable source files, review drafts and confirmed import lineage."""
from alembic import op
import sqlalchemy as sa

revision = '0003_import_batches'
down_revision = '0002_query_indexes'
branch_labels = depends_on = None


def upgrade():
    op.create_table('co_import_batch',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('source_sha256', sa.String(), nullable=False),
        sa.Column('source_base64', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('confirmed_at', sa.String(), nullable=True),
        sa.Column('rows', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['co_user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('created_by', 'source_sha256', 'kind', 'project_id'))
    op.create_index('ix_co_import_batch_created_by', 'co_import_batch', ['created_by'])


def downgrade():
    raise RuntimeError('导入来源不可破坏性降级，请恢复到新库')
