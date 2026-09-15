"""drop market_cap_cache (125-portfolio Monte Carlo removed)

Revision ID: a1c4e6f2b8d3
Revises: 59319d5cdf8b
Create Date: 2026-09-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c4e6f2b8d3'
down_revision = '59319d5cdf8b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('market_cap_cache')


def downgrade() -> None:
    op.create_table(
        'market_cap_cache',
        sa.Column('ticker', sa.String(length=16), nullable=False),
        sa.Column('market_cap', sa.Float(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('ticker'),
    )
