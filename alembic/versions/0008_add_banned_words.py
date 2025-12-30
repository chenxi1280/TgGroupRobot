"""add banned words feature

Revision ID: 0008_add_banned_words
Revises: 0007_add_anti_flood
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_add_banned_words"
down_revision = "0007_add_anti_flood"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "banned_words",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("word", sa.String(length=255), nullable=False),
        sa.Column("match_type", sa.String(length=16), nullable=False, server_default="contains"),
        sa.Column("action", sa.String(length=16), nullable=False, server_default="delete"),
        sa.Column("mute_duration", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("notify", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_message", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["bot.tg_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["bot.tg_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="bot",
    )
    op.create_index(op.f("ix_bot_banned_words_chat_id"), "banned_words", ["chat_id"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_banned_words_is_active"), "banned_words", ["is_active"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_banned_words_word"), "banned_words", ["word"], unique=False, schema="bot")


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_banned_words_word"), table_name="banned_words", schema="bot")
    op.drop_index(op.f("ix_bot_banned_words_is_active"), table_name="banned_words", schema="bot")
    op.drop_index(op.f("ix_bot_banned_words_chat_id"), table_name="banned_words", schema="bot")
    op.drop_table("banned_words", schema="bot")
