"""add auto reply feature

Revision ID: 0006_add_auto_reply
Revises: 0005_add_scheduled_messages
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_add_auto_reply"
down_revision = "0005_add_scheduled_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_reply_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("keywords", sa.JSONB(), nullable=False, server_default="[]"),
        sa.Column("reply_content", sa.Text(), nullable=False),
        sa.Column("match_type", sa.String(length=16), nullable=False, server_default="contains"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["bot.tg_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["bot.tg_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="bot",
    )
    op.create_index(op.f("ix_bot_auto_reply_rules_chat_id"), "auto_reply_rules", ["chat_id"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_auto_reply_rules_is_active"), "auto_reply_rules", ["is_active"], unique=False, schema="bot")


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_auto_reply_rules_is_active"), table_name="auto_reply_rules", schema="bot")
    op.drop_index(op.f("ix_bot_auto_reply_rules_chat_id"), table_name="auto_reply_rules", schema="bot")
    op.drop_table("auto_reply_rules", schema="bot")
