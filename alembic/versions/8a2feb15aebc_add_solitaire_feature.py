"""add solitaire feature

Revision ID: 8a2feb15aebc
Revises: 0010_add_invite_links
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8a2feb15aebc'
down_revision = '0010_add_invite_links'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solitaires",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("max_participants", sa.Integer(), nullable=True),
        sa.Column("entries", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["bot.tg_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["bot.tg_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="bot",
    )
    op.create_index(op.f("ix_bot_solitaires_chat_id"), "solitaires", ["chat_id"], unique=False, schema="bot")


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_solitaires_chat_id"), table_name="solitaires", schema="bot")
    op.drop_table("solitaires", schema="bot")
