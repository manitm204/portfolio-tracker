"""index constituents (Monte Carlo ticker universe)

Revision ID: 8f2a1c7d4e91
Revises: 71e32f4d396e
Create Date: 2026-08-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8f2a1c7d4e91'
down_revision = '71e32f4d396e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'index_constituents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('index_name', sa.String(length=16), nullable=False),
        sa.Column('ticker', sa.String(length=16), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('index_name', 'ticker', name='uq_index_member'),
    )
    with op.batch_alter_table('index_constituents', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_index_constituents_ticker'), ['ticker'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('index_constituents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_index_constituents_ticker'))
    op.drop_table('index_constituents')
