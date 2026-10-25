"""refresh_runs.provider (which market-data source a run used)

Revision ID: c5e2a9d1f7b3
Revises: a1c4e6f2b8d3
Create Date: 2026-10-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5e2a9d1f7b3'
down_revision = 'a1c4e6f2b8d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('refresh_runs') as batch_op:
        batch_op.add_column(sa.Column('provider', sa.String(length=16), nullable=True))
    # Every run before this migration used FMP.
    op.execute("UPDATE refresh_runs SET provider = 'fmp'")


def downgrade() -> None:
    with op.batch_alter_table('refresh_runs') as batch_op:
        batch_op.drop_column('provider')
