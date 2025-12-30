"""add welcome feature

Revision ID: 0004_add_welcome_feature
Revises: 0003_enhance_lottery_features
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_add_welcome_feature"
down_revision = "0003_enhance_lottery_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加进群欢迎相关字段到 chat_settings 表
    op.add_column(
        "chat_settings",
        sa.Column("welcome_enabled", sa.Boolean(), nullable=False, server_default="true"),
        schema="bot",
    )
    op.add_column(
        "chat_settings",
        sa.Column("welcome_message", sa.Text(), nullable=True),
        schema="bot",
    )


def downgrade() -> None:
    op.drop_column("chat_settings", "welcome_message", schema="bot")
    op.drop_column("chat_settings", "welcome_enabled", schema="bot")
