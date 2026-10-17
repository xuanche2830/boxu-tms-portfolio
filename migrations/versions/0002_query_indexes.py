"""Indexes for scoped lists and per-order history. No business rows are rewritten."""
from alembic import op

revision = '0002_query_indexes'
down_revision = '0001_collaboration'
branch_labels = depends_on = None

INDEXES = [
    ('ix_co_grant_scope', 'co_grant', ['kind', 'resource_id', 'user_id']),
    ('ix_pl_event_order_time', 'pl_event', ['order_id', 'recorded_at']),
    ('ix_pl_issue_order_status', 'pl_issue', ['order_id', 'status']),
    ('ix_pl_order_partner_status', 'pl_order', ['partner_id', 'status']),
]


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
