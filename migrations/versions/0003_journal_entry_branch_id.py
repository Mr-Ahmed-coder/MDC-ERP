"""Add branch_id to journal_entry table.

Revision ID: 0003_journal_entry_branch_id
Revises: 0002_record_lifecycle
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_journal_entry_branch_id'
down_revision = '0002_record_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c['name'] for c in inspector.get_columns('journal_entry')]
    if 'branch_id' not in cols:
        op.add_column('journal_entry', sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branch.id'), nullable=True))
        existing_idx = {idx['name'] for idx in inspector.get_indexes('journal_entry')}
        if 'ix_journal_entry_branch_id' not in existing_idx:
            op.create_index('ix_journal_entry_branch_id', 'journal_entry', ['branch_id'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_idx = {idx['name'] for idx in inspector.get_indexes('journal_entry')}
    if 'ix_journal_entry_branch_id' in existing_idx:
        op.drop_index('ix_journal_entry_branch_id', table_name='journal_entry')
    cols = [c['name'] for c in inspector.get_columns('journal_entry')]
    if 'branch_id' in cols:
        op.drop_column('journal_entry', 'branch_id')
