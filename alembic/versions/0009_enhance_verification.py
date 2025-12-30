"""enhance verification feature

Revision ID: 0009_enhance_verification
Revises: 0008_add_banned_words
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_enhance_verification"
down_revision = "0008_add_banned_words"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加验证模式字段到 chat_settings 表
    op.add_column(
        "chat_settings",
        sa.Column("verification_mode", sa.String(length=16), nullable=False, server_default="button"),
        schema="bot",
    )

    # 添加验证类型、问题、答案字段到 verification_challenges 表
    op.add_column(
        "verification_challenges",
        sa.Column("verification_type", sa.String(length=16), nullable=False, server_default="button"),
        schema="bot",
    )
    op.add_column(
        "verification_challenges",
        sa.Column("question", sa.Text(), nullable=True),
        schema="bot",
    )
    op.add_column(
        "verification_challenges",
        sa.Column("answer", sa.String(length=64), nullable=True),
        schema="bot",
    )


def downgrade() -> None:
    op.drop_column("verification_challenges", "answer", schema="bot")
    op.drop_column("verification_challenges", "question", schema="bot")
    op.drop_column("verification_challenges", "verification_type", schema="bot")
    op.drop_column("chat_settings", "verification_mode", schema="bot")
