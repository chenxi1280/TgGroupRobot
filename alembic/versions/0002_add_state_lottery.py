"""add conversation state and lottery

Revision ID: 0002_add_state_lottery
Revises: 0001_init
Create Date: 2025-12-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_add_state_lottery"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 对话状态表
    op.create_table(
        "conversation_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_type", sa.String(length=32), nullable=False),
        sa.Column("state_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_conversation_state"),
        schema="bot",
    )
    op.create_index("ix_conversation_states_chat_id", "conversation_states", ["chat_id"], schema="bot")
    op.create_index("ix_conversation_states_user_id", "conversation_states", ["user_id"], schema="bot")
    op.create_index("ix_conversation_states_state_type", "conversation_states", ["state_type"], schema="bot")

    # 抽奖表
    op.create_table(
        "lotteries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=False, server_default="通用抽奖"),
        sa.Column("draw_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prizes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True),
        schema="bot",
    )
    op.create_index("ix_lotteries_chat_id", "lotteries", ["chat_id"], schema="bot")
    op.create_index("ix_lotteries_draw_time", "lotteries", ["draw_time"], schema="bot")
    op.create_index("ix_lotteries_status", "lotteries", ["status"], schema="bot")

    # 抽奖参与者表
    op.create_table(
        "lottery_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lottery_id", sa.Integer(), sa.ForeignKey("bot.lotteries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lottery_id", "user_id", name="uq_lottery_participant"),
        schema="bot",
    )
    op.create_index("ix_lottery_participants_lottery_id", "lottery_participants", ["lottery_id"], schema="bot")
    op.create_index("ix_lottery_participants_user_id", "lottery_participants", ["user_id"], schema="bot")


def downgrade() -> None:
    op.drop_table("lottery_participants", schema="bot")
    op.drop_table("lotteries", schema="bot")
    op.drop_table("conversation_states", schema="bot")

