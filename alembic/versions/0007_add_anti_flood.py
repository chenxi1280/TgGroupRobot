"""add anti flood feature

Revision ID: 0007_add_anti_flood
Revises: 0006_add_auto_reply
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_add_anti_flood"
down_revision = "0006_add_auto_reply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加反刷屏相关字段到 chat_settings 表
    op.add_column(
        "chat_settings",
        sa.Column("anti_flood_enabled", sa.Boolean(), nullable=False, server_default="false"),
        schema="bot",
    )
    op.add_column(
        "chat_settings",
        sa.Column("anti_flood_messages", sa.Integer(), nullable=False, server_default="5"),
        schema="bot",
    )
    op.add_column(
        "chat_settings",
        sa.Column("anti_flood_seconds", sa.Integer(), nullable=False, server_default="5"),
        schema="bot",
    )
    op.add_column(
        "chat_settings",
        sa.Column("anti_flood_action", sa.String(length=32), nullable=False, server_default="mute"),
        schema="bot",
    )
    op.add_column(
        "chat_settings",
        sa.Column("anti_flood_mute_duration", sa.Integer(), nullable=False, server_default="60"),
        schema="bot",
    )


def downgrade() -> None:
    op.drop_column("chat_settings", "anti_flood_mute_duration", schema="bot")
    op.drop_column("chat_settings", "anti_flood_action", schema="bot")
    op.drop_column("chat_settings", "anti_flood_seconds", schema="bot")
    op.drop_column("chat_settings", "anti_flood_messages", schema="bot")
    op.drop_column("chat_settings", "anti_flood_enabled", schema="bot")
