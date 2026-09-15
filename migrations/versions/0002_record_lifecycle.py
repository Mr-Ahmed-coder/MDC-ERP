"""Record lifecycle archive ledger.

Revision ID: 0002_record_lifecycle
Revises: 0001_financial_integrity
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_record_lifecycle'
down_revision = '0001_financial_integrity'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'record_archive' not in inspector.get_table_names():
        op.create_table(
            'record_archive',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('entity_type', sa.String(length=80), nullable=False),
            sa.Column('entity_id', sa.Integer(), nullable=False),
            sa.Column('label', sa.String(length=200)),
            sa.Column('snapshot', sa.Text()),
            sa.Column('reason', sa.String(length=255), nullable=False),
            sa.Column('archived_by', sa.String(length=80), nullable=False),
            sa.Column('archived_at', sa.DateTime(), nullable=False),
            sa.Column('restored_by', sa.String(length=80)),
            sa.Column('restored_at', sa.DateTime()),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    existing = {idx['name'] for idx in sa.inspect(op.get_bind()).get_indexes('record_archive')}
    for name, columns in (
        ('ix_record_archive_entity_type', ['entity_type']),
        ('ix_record_archive_entity_id', ['entity_id']),
        ('ix_record_archive_active', ['active']),
    ):
        if name not in existing:
            op.create_index(name, 'record_archive', columns)


def downgrade():
    op.drop_index('ix_record_archive_active', table_name='record_archive')
    op.drop_index('ix_record_archive_entity_id', table_name='record_archive')
    op.drop_index('ix_record_archive_entity_type', table_name='record_archive')
    op.drop_table('record_archive')
