"""add scheduled messages feature

Revision ID: 0005_add_scheduled_messages
Revises: 0004_add_welcome_feature
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_add_scheduled_messages"
down_revision = "0004_add_welcome_feature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("next_send_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["bot.tg_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["bot.tg_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="bot",
    )
    op.create_index(op.f("ix_bot_scheduled_messages_chat_id"), "scheduled_messages", ["chat_id"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_scheduled_messages_is_active"), "scheduled_messages", ["is_active"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_scheduled_messages_next_send_time"), "scheduled_messages", ["next_send_time"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_scheduled_messages_schedule_type"), "scheduled_messages", ["schedule_type"], unique=False, schema="bot")


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_scheduled_messages_schedule_type"), table_name="scheduled_messages", schema="bot")
    op.drop_index(op.f("ix_bot_scheduled_messages_next_send_time"), table_name="scheduled_messages", schema="bot")
    op.drop_index(op.f("ix_bot_scheduled_messages_is_active"), table_name="scheduled_messages", schema="bot")
    op.drop_index(op.f("ix_bot_scheduled_messages_chat_id"), table_name="scheduled_messages", schema="bot")
    op.drop_table("scheduled_messages", schema="bot")
