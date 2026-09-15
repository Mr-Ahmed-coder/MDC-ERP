"""Initial complete MDC ERP schema baseline.

This revision moves first-install schema creation into Alembic. It deliberately
uses the application metadata only inside the migration; runtime application
startup never calls ``create_all`` in production.

Revision ID: 0000_initial_schema
Revises:
"""
from alembic import op

from mdc_erp.extensions import db
from mdc_erp import models  # noqa: F401  # register all model tables

revision = "0000_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    db.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    db.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
