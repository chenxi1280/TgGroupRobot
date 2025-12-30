"""add lottery draw mode

Revision ID: ce4d9ba534b6
Revises: 8a2feb15aebc
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'ce4d9ba534b6'
down_revision = '8a2feb15aebc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lotteries', sa.Column('draw_mode', sa.String(length=16), nullable=False, server_default='manual'), schema='bot')


def downgrade() -> None:
    op.drop_column('lotteries', 'draw_mode', schema='bot')
