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
    op.create_table(
        "tg_users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "tg_chats",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chat_settings",
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), primary_key=True),
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
    )

    op.create_table(
        "chat_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
    )
    op.create_index("ix_chat_members_chat_id", "chat_members", ["chat_id"])
    op.create_index("ix_chat_members_user_id", "chat_members", ["user_id"])

    op.create_table(
        "points_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_points_account"),
    )
    op.create_index("ix_points_accounts_chat_id", "points_accounts", ["chat_id"])
    op.create_index("ix_points_accounts_user_id", "points_accounts", ["user_id"])

    op.create_table(
        "points_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("txn_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_points_transactions_chat_id", "points_transactions", ["chat_id"])
    op.create_index("ix_points_transactions_user_id", "points_transactions", ["user_id"])
    op.create_index("ix_points_transactions_txn_type", "points_transactions", ["txn_type"])

    op.create_table(
        "sign_in_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sign_date", sa.Date(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", "sign_date", name="uq_sign_in_daily"),
    )
    op.create_index("ix_sign_in_logs_chat_id", "sign_in_logs", ["chat_id"])
    op.create_index("ix_sign_in_logs_user_id", "sign_in_logs", ["user_id"])

    op.create_table(
        "moderation_violations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_moderation_violations_chat_id", "moderation_violations", ["chat_id"])
    op.create_index("ix_moderation_violations_user_id", "moderation_violations", ["user_id"])

    op.create_table(
        "verification_challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_verification_active"),
    )
    op.create_index("ix_verification_challenges_chat_id", "verification_challenges", ["chat_id"])
    op.create_index("ix_verification_challenges_user_id", "verification_challenges", ["user_id"])
    op.create_index("ix_verification_challenges_token", "verification_challenges", ["token"])
    op.create_index("ix_verification_challenges_expires_at", "verification_challenges", ["expires_at"])

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
    )
    op.create_index("ix_subscription_plans_code", "subscription_plans", ["code"])

    op.create_table(
        "chat_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", name="uq_chat_subscription"),
    )
    op.create_index("ix_chat_subscriptions_chat_id", "chat_subscriptions", ["chat_id"])
    op.create_index("ix_chat_subscriptions_status", "chat_subscriptions", ["status"])
    op.create_index("ix_chat_subscriptions_end_at", "chat_subscriptions", ["end_at"])

    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("tg_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("tg_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ad_campaigns_chat_id", "ad_campaigns", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_ad_campaigns_chat_id", table_name="ad_campaigns")
    op.drop_table("ad_campaigns")

    op.drop_index("ix_chat_subscriptions_end_at", table_name="chat_subscriptions")
    op.drop_index("ix_chat_subscriptions_status", table_name="chat_subscriptions")
    op.drop_index("ix_chat_subscriptions_chat_id", table_name="chat_subscriptions")
    op.drop_table("chat_subscriptions")

    op.drop_index("ix_subscription_plans_code", table_name="subscription_plans")
    op.drop_table("subscription_plans")

    op.drop_index("ix_verification_challenges_expires_at", table_name="verification_challenges")
    op.drop_index("ix_verification_challenges_token", table_name="verification_challenges")
    op.drop_index("ix_verification_challenges_user_id", table_name="verification_challenges")
    op.drop_index("ix_verification_challenges_chat_id", table_name="verification_challenges")
    op.drop_table("verification_challenges")

    op.drop_index("ix_moderation_violations_user_id", table_name="moderation_violations")
    op.drop_index("ix_moderation_violations_chat_id", table_name="moderation_violations")
    op.drop_table("moderation_violations")

    op.drop_index("ix_sign_in_logs_user_id", table_name="sign_in_logs")
    op.drop_index("ix_sign_in_logs_chat_id", table_name="sign_in_logs")
    op.drop_table("sign_in_logs")

    op.drop_index("ix_points_transactions_txn_type", table_name="points_transactions")
    op.drop_index("ix_points_transactions_user_id", table_name="points_transactions")
    op.drop_index("ix_points_transactions_chat_id", table_name="points_transactions")
    op.drop_table("points_transactions")

    op.drop_index("ix_points_accounts_user_id", table_name="points_accounts")
    op.drop_index("ix_points_accounts_chat_id", table_name="points_accounts")
    op.drop_table("points_accounts")

    op.drop_index("ix_chat_members_user_id", table_name="chat_members")
    op.drop_index("ix_chat_members_chat_id", table_name="chat_members")
    op.drop_table("chat_members")

    op.drop_table("chat_settings")
    op.drop_table("tg_chats")
    op.drop_table("tg_users")



