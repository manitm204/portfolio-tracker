"""sleeve accounts and index heatmap snapshot

Revision ID: d7f3b1a2c9e4
Revises: c5e2a9d1f7b3
Create Date: 2026-11-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd7f3b1a2c9e4'
down_revision = 'c5e2a9d1f7b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('start_date', existing_type=sa.Date(), nullable=True)
        batch_op.add_column(sa.Column('sleeve_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('planned_start', sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # The single pre-sleeve account stays in the database, out of the portfolio.
    op.execute("UPDATE accounts SET archived = 1 WHERE id = 'PORTFOLIO_5'")

    with op.batch_alter_table('index_constituents') as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('weight', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('period_returns', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('returns_as_of', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('index_constituents') as batch_op:
        batch_op.drop_column('returns_as_of')
        batch_op.drop_column('period_returns')
        batch_op.drop_column('weight')
        batch_op.drop_column('name')
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.drop_column('archived')
        batch_op.drop_column('planned_start')
        batch_op.drop_column('sleeve_number')
        batch_op.alter_column('start_date', existing_type=sa.Date(), nullable=False)
