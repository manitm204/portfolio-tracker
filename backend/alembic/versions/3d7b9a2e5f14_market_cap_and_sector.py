"""market cap cache + index constituent sector (125-portfolio Monte Carlo)

Revision ID: 3d7b9a2e5f14
Revises: 8f2a1c7d4e91
Create Date: 2026-08-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '3d7b9a2e5f14'
down_revision = '8f2a1c7d4e91'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('index_constituents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sector', sa.String(length=64), nullable=True))

    op.create_table(
        'market_cap_cache',
        sa.Column('ticker', sa.String(length=16), nullable=False),
        sa.Column('market_cap', sa.Float(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('ticker'),
    )


def downgrade() -> None:
    op.drop_table('market_cap_cache')
    with op.batch_alter_table('index_constituents', schema=None) as batch_op:
        batch_op.drop_column('sector')
