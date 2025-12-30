"""enhance lottery features

Revision ID: 0003_enhance_lottery_features
Revises: 0002_add_state_lottery
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_enhance_lottery_features"
down_revision = "0002_add_state_lottery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 修改 lotteries 表，添加新字段
    op.add_column(
        "lotteries",
        sa.Column("description", sa.Text(), nullable=True),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("min_points", sa.Integer(), nullable=False, server_default="0"),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("max_participants", sa.Integer(), nullable=False, server_default="0"),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("participation_cost", sa.Integer(), nullable=False, server_default="0"),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("join_start_time", sa.DateTime(timezone=True), nullable=True),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("join_end_time", sa.DateTime(timezone=True), nullable=True),
        schema="bot",
    )
    op.add_column(
        "lotteries",
        sa.Column("requirement_days", sa.Integer(), nullable=False, server_default="0"),
        schema="bot",
    )

    # 修改 lottery_participants 表，添加 points_balance 字段
    op.add_column(
        "lottery_participants",
        sa.Column("points_balance", sa.Integer(), nullable=False, server_default="0"),
        schema="bot",
    )

    # 创建 lottery_winners 表
    op.create_table(
        "lottery_winners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lottery_id", sa.Integer(), sa.ForeignKey("bot.lotteries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prize_name", sa.String(length=255), nullable=False),
        sa.Column("prize_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )
    op.create_index("ix_lottery_winners_lottery_id", "lottery_winners", ["lottery_id"], schema="bot")
    op.create_index("ix_lottery_winners_user_id", "lottery_winners", ["user_id"], schema="bot")


def downgrade() -> None:
    # 删除 lottery_winners 表
    op.drop_table("lottery_winners", schema="bot")

    # 删除 lottery_participants 表的 points_balance 字段
    op.drop_column("lottery_participants", "points_balance", schema="bot")

    # 删除 lotteries 表的新增字段
    op.drop_column("lotteries", "requirement_days", schema="bot")
    op.drop_column("lotteries", "join_end_time", schema="bot")
    op.drop_column("lotteries", "join_start_time", schema="bot")
    op.drop_column("lotteries", "participation_cost", schema="bot")
    op.drop_column("lotteries", "max_participants", schema="bot")
    op.drop_column("lotteries", "min_points", schema="bot")
    op.drop_column("lotteries", "description", schema="bot")
