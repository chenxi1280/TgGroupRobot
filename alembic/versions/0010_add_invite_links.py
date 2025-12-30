"""add invite link management

Revision ID: 0010_add_invite_links
Revises: 0009_enhance_verification
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_add_invite_links"
down_revision = "0009_enhance_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invite_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("invite_link", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("member_limit", sa.Integer(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expire_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creates_join_request", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["bot.tg_chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["bot.tg_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="bot",
    )
    op.create_index(op.f("ix_bot_invite_links_chat_id"), "invite_links", ["chat_id"], unique=False, schema="bot")
    op.create_index(op.f("ix_bot_invite_links_invite_link"), "invite_links", ["invite_link"], unique=False, schema="bot")


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_invite_links_invite_link"), table_name="invite_links", schema="bot")
    op.drop_index(op.f("ix_bot_invite_links_chat_id"), table_name="invite_links", schema="bot")
    op.drop_table("invite_links", schema="bot")
