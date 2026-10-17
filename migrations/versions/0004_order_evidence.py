"""Private transport evidence, explicit requests and review history."""
from alembic import op
import sqlalchemy as sa

revision = '0004_order_evidence'
down_revision = '0003_import_batches'
branch_labels = depends_on = None


def upgrade():
    op.create_table('co_evidence_requirement',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('unit_id', sa.String(), nullable=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['pl_order.id']),
        sa.ForeignKeyConstraint(['unit_id'], ['pl_unit.id']),
        sa.ForeignKeyConstraint(['created_by'], ['co_user.id']), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_co_evidence_requirement_order_id', 'co_evidence_requirement', ['order_id'])
    op.create_table('co_evidence_file',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('unit_id', sa.String(), nullable=True),
        sa.Column('requirement_id', sa.String(), nullable=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('media_type', sa.String(), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('storage_key', sa.String(), nullable=False),
        sa.Column('uploaded_by', sa.String(), nullable=False),
        sa.Column('uploaded_at', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('review_status', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('command_id', sa.String(), nullable=False),
        sa.Column('signature', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['pl_order.id']),
        sa.ForeignKeyConstraint(['unit_id'], ['pl_unit.id']),
        sa.ForeignKeyConstraint(['requirement_id'], ['co_evidence_requirement.id']),
        sa.ForeignKeyConstraint(['uploaded_by'], ['co_user.id']),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('storage_key'), sa.UniqueConstraint('command_id'))
    op.create_index('ix_co_evidence_file_order_id', 'co_evidence_file', ['order_id'])
    op.create_table('co_evidence_review',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('evidence_id', sa.String(), nullable=False),
        sa.Column('reviewer_id', sa.String(), nullable=False),
        sa.Column('outcome', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['evidence_id'], ['co_evidence_file.id']),
        sa.ForeignKeyConstraint(['reviewer_id'], ['co_user.id']), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_co_evidence_review_evidence_id', 'co_evidence_review', ['evidence_id'])


def downgrade():
    raise RuntimeError('凭证记录不可破坏性降级，请恢复到新库')
