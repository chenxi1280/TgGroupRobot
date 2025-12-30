from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base
from bot.models.enums import (
    AutoReplyMatchType,
    BannedWordMatchType,
    ChatType,
    InviteLinkStatus,
    LotteryDrawMode,
    MemberRole,
    ModerationAction,
    PointsTxnType,
    ScheduleType,
    SolitaireStatus,
    SubscriptionStatus,
    VerificationMode,
)


class TgUser(Base):
    __tablename__ = "tg_users"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class TgChat(Base):
    __tablename__ = "tg_chats"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram chat_id（群）
    type: Mapped[str] = mapped_column(String(32), default=ChatType.supergroup.value)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    settings: Mapped["ChatSettings"] = relationship(back_populates="chat", uselist=False)


class ChatSettings(Base):
    __tablename__ = "chat_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)

    # 多语言：默认中文
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")

    # 签到积分
    sign_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sign_points: Mapped[int] = mapped_column(Integer, default=5)
    sign_cooldown_hours: Mapped[int] = mapped_column(Integer, default=20)

    # 新人验证/限制
    verification_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_mode: Mapped[str] = mapped_column(String(16), default=VerificationMode.button.value)  # 验证模式
    verification_timeout_seconds: Mapped[int] = mapped_column(Integer, default=180)
    verification_restrict_can_send: Mapped[bool] = mapped_column(Boolean, default=False)

    # 内容审核（基础）
    moderation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    moderation_block_links: Mapped[bool] = mapped_column(Boolean, default=True)
    moderation_action: Mapped[str] = mapped_column(String(32), default=ModerationAction.delete.value)
    moderation_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 简易关键词名单

    # 广告 & 商业化开关位
    ads_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monetization_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # 进群欢迎
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # 自定义欢迎消息模板

    # 反刷屏
    anti_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否启用反刷屏
    anti_flood_messages: Mapped[int] = mapped_column(Integer, default=5)  # 触发消息数量
    anti_flood_seconds: Mapped[int] = mapped_column(Integer, default=5)  # 时间窗口（秒）
    anti_flood_action: Mapped[str] = mapped_column(String(32), default="mute")  # 惩罚动作: mute/delete/ban
    anti_flood_mute_duration: Mapped[int] = mapped_column(Integer, default=60)  # 禁言时长（秒）

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    chat: Mapped[TgChat] = relationship(back_populates="settings")


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default=MemberRole.member.value)

    joined_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsAccount(Base):
    __tablename__ = "points_accounts"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_points_account"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsTransaction(Base):
    __tablename__ = "points_transactions"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    txn_type: Mapped[str] = mapped_column(String(32), default=PointsTxnType.sign_in.value, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class SignInLog(Base):
    __tablename__ = "sign_in_logs"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "sign_date", name="uq_sign_in_daily"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    sign_date: Mapped[dt.date] = mapped_column(default=lambda: dt.datetime.now(dt.UTC).date())
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ModerationViolation(Base):
    __tablename__ = "moderation_violations"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule: Mapped[str] = mapped_column(String(64))  # e.g. "block_links" / "keyword"
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(32), default=ModerationAction.delete.value)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_verification_active"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    solved: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_type: Mapped[str] = mapped_column(String(16), default=VerificationMode.button.value)  # 验证类型
    question: Mapped[str | None] = mapped_column(Text, nullable=True)  # 问题（数学题等）
    answer: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 答案
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # free/pro/monthly/yearly
    name: Mapped[str] = mapped_column(String(64))
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    feature_flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ChatSubscription(Base):
    __tablename__ = "chat_subscriptions"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_chat_subscription"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.subscription_plans.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default=SubscriptionStatus.active.value, index=True)
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ConversationState(Base):
    """用户对话状态：用于多步骤流程（如创建抽奖）"""
    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_conversation_state"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    state_type: Mapped[str] = mapped_column(String(32), index=True)  # e.g. "lottery_create"
    state_data: Mapped[dict] = mapped_column(JSONB, default=dict)  # 保存流程中的临时数据
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class Lottery(Base):
    """抽奖活动"""
    __tablename__ = "lotteries"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(128), default="通用抽奖")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 抽奖描述说明
    draw_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)  # 开奖时间
    prizes: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # [{"name": "1USDT", "quantity": 1}, ...]
    draw_mode: Mapped[str] = mapped_column(String(16), default=LotteryDrawMode.manual.value)  # 开奖模式: random/manual
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/completed/cancelled
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 抽奖消息ID
    # 参与限制条件
    min_points: Mapped[int] = mapped_column(Integer, default=0)  # 最低积分要求
    max_participants: Mapped[int] = mapped_column(Integer, default=0)  # 最大参与人数（0=无限制）
    participation_cost: Mapped[int] = mapped_column(Integer, default=0)  # 参与费用（积分）
    join_start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 参与开始时间
    join_end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 参与结束时间
    requirement_days: Mapped[int] = mapped_column(Integer, default=0)  # 入群天数要求
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    drawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LotteryParticipant(Base):
    """抽奖参与者"""
    __tablename__ = "lottery_participants"
    __table_args__ = (
        UniqueConstraint("lottery_id", "user_id", name="uq_lottery_participant"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lottery_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.lotteries.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)  # 参与时的积分余额快照
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class LotteryWinner(Base):
    """抽奖中奖记录"""
    __tablename__ = "lottery_winners"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lottery_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.lotteries.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    prize_name: Mapped[str] = mapped_column(String(255))  # 中奖奖品名称
    prize_index: Mapped[int] = mapped_column(Integer)  # 奖品索引
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ScheduledMessage(Base):
    """定时消息"""
    __tablename__ = "scheduled_messages"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text)  # 消息内容
    schedule_type: Mapped[str] = mapped_column(String(32), default=ScheduleType.none.value, index=True)  # 定时类型
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 自定义间隔分钟数
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # 是否激活
    next_send_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)  # 下次发送时间
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 上次发送时间
    send_count: Mapped[int] = mapped_column(Integer, default=0)  # 已发送次数
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AutoReplyRule(Base):
    """自动回复规则"""
    __tablename__ = "auto_reply_rules"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 触发关键词列表
    reply_content: Mapped[str] = mapped_column(Text)  # 回复内容
    match_type: Mapped[str] = mapped_column(String(16), default=AutoReplyMatchType.contains.value)  # 匹配类型
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # 是否激活
    match_count: Mapped[int] = mapped_column(Integer, default=0)  # 匹配次数统计
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否区分大小写
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class BannedWord(Base):
    """违禁词"""
    __tablename__ = "banned_words"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    word: Mapped[str] = mapped_column(String(255), index=True)  # 违禁词
    match_type: Mapped[str] = mapped_column(String(16), default=BannedWordMatchType.contains.value)  # 匹配类型
    action: Mapped[str] = mapped_column(String(16), default="delete")  # 惩罚动作: delete/mute/ban
    mute_duration: Mapped[int] = mapped_column(Integer, default=60)  # 禁言时长（秒）
    notify: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否发送删除提醒
    notify_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # 自定义提醒消息
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # 是否激活
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)  # 触发次数统计
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否区分大小写
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class InviteLink(Base):
    """群组邀请链接管理"""
    __tablename__ = "invite_links"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    invite_link: Mapped[str] = mapped_column(String(255), index=True)  # Telegram邀请链接
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 链接名称
    status: Mapped[str] = mapped_column(String(16), default=InviteLinkStatus.active.value)  # 状态
    member_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 成员数量限制（0=无限制）
    member_count: Mapped[int] = mapped_column(Integer, default=0)  # 当前成员数
    expire_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 过期时间
    creates_join_request: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否需要审核
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class Solitaire(Base):
    """群组接龙活动"""
    __tablename__ = "solitaires"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)  # 接龙标题
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 描述说明
    status: Mapped[str] = mapped_column(String(16), default=SolitaireStatus.active.value)  # 状态
    max_participants: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 最大参与人数（null=无限制）
    entries: Mapped[list] = mapped_column(JSONB, default=list)  # 参与记录 [{"user_id": 123, "username": "xxx", "content": "xxx", "joined_at": "2024-01-01"}]
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 接龙消息ID（用于更新）
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )




