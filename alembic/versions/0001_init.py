"""init tables

Revision ID: 0001_init
Revises:
Create Date: 2025-12-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建 bot schema（如果不存在）
    op.execute("CREATE SCHEMA IF NOT EXISTS bot")
    
    op.create_table(
        "tg_users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )

    op.create_table(
        "tg_chats",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )

    op.create_table(
        "chat_settings",
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("sign_enabled", sa.Boolean(), nullable=False),
        sa.Column("sign_points", sa.Integer(), nullable=False),
        sa.Column("sign_cooldown_hours", sa.Integer(), nullable=False),
        sa.Column("verification_enabled", sa.Boolean(), nullable=False),
        sa.Column("verification_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("verification_restrict_can_send", sa.Boolean(), nullable=False),
        sa.Column("moderation_enabled", sa.Boolean(), nullable=False),
        sa.Column("moderation_block_links", sa.Boolean(), nullable=False),
        sa.Column("moderation_action", sa.String(length=32), nullable=False),
        sa.Column("moderation_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ads_enabled", sa.Boolean(), nullable=False),
        sa.Column("monetization_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )

    op.create_table(
        "chat_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
        schema="bot",
    )
    op.create_index("ix_chat_members_chat_id", "chat_members", ["chat_id"], schema="bot")
    op.create_index("ix_chat_members_user_id", "chat_members", ["user_id"], schema="bot")

    op.create_table(
        "points_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_points_account"),
        schema="bot",
    )
    op.create_index("ix_points_accounts_chat_id", "points_accounts", ["chat_id"], schema="bot")
    op.create_index("ix_points_accounts_user_id", "points_accounts", ["user_id"], schema="bot")

    op.create_table(
        "points_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("txn_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )
    op.create_index("ix_points_transactions_chat_id", "points_transactions", ["chat_id"], schema="bot")
    op.create_index("ix_points_transactions_user_id", "points_transactions", ["user_id"], schema="bot")
    op.create_index("ix_points_transactions_txn_type", "points_transactions", ["txn_type"], schema="bot")

    op.create_table(
        "sign_in_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sign_date", sa.Date(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", "sign_date", name="uq_sign_in_daily"),
        schema="bot",
    )
    op.create_index("ix_sign_in_logs_chat_id", "sign_in_logs", ["chat_id"], schema="bot")
    op.create_index("ix_sign_in_logs_user_id", "sign_in_logs", ["user_id"], schema="bot")

    op.create_table(
        "moderation_violations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )
    op.create_index("ix_moderation_violations_chat_id", "moderation_violations", ["chat_id"], schema="bot")
    op.create_index("ix_moderation_violations_user_id", "moderation_violations", ["user_id"], schema="bot")

    op.create_table(
        "verification_challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_verification_active"),
        schema="bot",
    )
    op.create_index("ix_verification_challenges_chat_id", "verification_challenges", ["chat_id"], schema="bot")
    op.create_index("ix_verification_challenges_user_id", "verification_challenges", ["user_id"], schema="bot")
    op.create_index("ix_verification_challenges_token", "verification_challenges", ["token"], schema="bot")
    op.create_index("ix_verification_challenges_expires_at", "verification_challenges", ["expires_at"], schema="bot")

    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("feature_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_subscription_plans_code"),
        schema="bot",
    )
    op.create_index("ix_subscription_plans_code", "subscription_plans", ["code"], schema="bot")

    op.create_table(
        "chat_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("bot.subscription_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", name="uq_chat_subscription"),
        schema="bot",
    )
    op.create_index("ix_chat_subscriptions_chat_id", "chat_subscriptions", ["chat_id"], schema="bot")
    op.create_index("ix_chat_subscriptions_status", "chat_subscriptions", ["status"], schema="bot")
    op.create_index("ix_chat_subscriptions_end_at", "chat_subscriptions", ["end_at"], schema="bot")

    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="bot",
    )
    op.create_index("ix_ad_campaigns_chat_id", "ad_campaigns", ["chat_id"], schema="bot")


def downgrade() -> None:
    op.drop_index("ix_ad_campaigns_chat_id", table_name="ad_campaigns", schema="bot")
    op.drop_table("ad_campaigns", schema="bot")

    op.drop_index("ix_chat_subscriptions_end_at", table_name="chat_subscriptions", schema="bot")
    op.drop_index("ix_chat_subscriptions_status", table_name="chat_subscriptions", schema="bot")
    op.drop_index("ix_chat_subscriptions_chat_id", table_name="chat_subscriptions", schema="bot")
    op.drop_table("chat_subscriptions", schema="bot")

    op.drop_index("ix_subscription_plans_code", table_name="subscription_plans", schema="bot")
    op.drop_table("subscription_plans", schema="bot")

    op.drop_index("ix_verification_challenges_expires_at", table_name="verification_challenges", schema="bot")
    op.drop_index("ix_verification_challenges_token", table_name="verification_challenges", schema="bot")
    op.drop_index("ix_verification_challenges_user_id", table_name="verification_challenges", schema="bot")
    op.drop_index("ix_verification_challenges_chat_id", table_name="verification_challenges", schema="bot")
    op.drop_table("verification_challenges", schema="bot")

    op.drop_index("ix_moderation_violations_user_id", table_name="moderation_violations", schema="bot")
    op.drop_index("ix_moderation_violations_chat_id", table_name="moderation_violations", schema="bot")
    op.drop_table("moderation_violations", schema="bot")

    op.drop_index("ix_sign_in_logs_user_id", table_name="sign_in_logs", schema="bot")
    op.drop_index("ix_sign_in_logs_chat_id", table_name="sign_in_logs", schema="bot")
    op.drop_table("sign_in_logs", schema="bot")

    op.drop_index("ix_points_transactions_txn_type", table_name="points_transactions", schema="bot")
    op.drop_index("ix_points_transactions_user_id", table_name="points_transactions", schema="bot")
    op.drop_index("ix_points_transactions_chat_id", table_name="points_transactions", schema="bot")
    op.drop_table("points_transactions", schema="bot")

    op.drop_index("ix_points_accounts_user_id", table_name="points_accounts", schema="bot")
    op.drop_index("ix_points_accounts_chat_id", table_name="points_accounts", schema="bot")
    op.drop_table("points_accounts", schema="bot")

    op.drop_index("ix_chat_members_user_id", table_name="chat_members", schema="bot")
    op.drop_index("ix_chat_members_chat_id", table_name="chat_members", schema="bot")
    op.drop_table("chat_members", schema="bot")

    op.drop_table("chat_settings", schema="bot")
    op.drop_table("tg_chats", schema="bot")
    op.drop_table("tg_users", schema="bot")
    
    # 删除 bot schema（可选，谨慎使用）
    # op.execute("DROP SCHEMA IF EXISTS bot CASCADE")





