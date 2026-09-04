"""rebalance history (model_target effective dating + rebalance_events)

Revision ID: 59319d5cdf8b
Revises: 3d7b9a2e5f14
Create Date: 2026-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '59319d5cdf8b'
down_revision = '3d7b9a2e5f14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('model_targets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('activated_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('deactivated_date', sa.Date(), nullable=True))

    op.create_table(
        'rebalance_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(length=64), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('before_snapshot', sa.Text(), nullable=False),
        sa.Column('after_snapshot', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rebalance_events', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_rebalance_events_account_id'), ['account_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_rebalance_events_event_date'), ['event_date'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('rebalance_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rebalance_events_event_date'))
        batch_op.drop_index(batch_op.f('ix_rebalance_events_account_id'))
    op.drop_table('rebalance_events')

    with op.batch_alter_table('model_targets', schema=None) as batch_op:
        batch_op.drop_column('deactivated_date')
        batch_op.drop_column('activated_date')
