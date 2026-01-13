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
    sign_consecutive_days: Mapped[int] = mapped_column(Integer, default=0)  # 连续签到多少天奖励
    sign_consecutive_bonus: Mapped[int] = mapped_column(Integer, default=0)  # 连续签到奖励积分

    # 发言积分
    message_points_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    message_points: Mapped[int] = mapped_column(Integer, default=1)
    message_points_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 每日上限，null=无限制
    message_min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 最小字数，null=无限制

    # 邀请积分
    invite_points_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_points: Mapped[int] = mapped_column(Integer, default=1)
    invite_points_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 每日上限，null=无限制

    # 邀请链接配置
    invite_link_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否开启用户生成链接
    invite_link_notify: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否通知新成员加入
    invite_link_expire_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 链接过期的天数，null=无限制
    invite_link_max_joins: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 单个链接最大加入人数，null=无限制
    invite_link_user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 每个用户可生成链接数量上限，null=无限制

    # 自动删除配置
    auto_delete_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否开启自动删除
    auto_delete_join: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除进群消息
    auto_delete_left: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除退群消息
    auto_delete_pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除置顶消息
    auto_delete_avatar: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除修改头像消息
    auto_delete_title: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除修改群名消息
    auto_delete_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动删除匿名管理员消息

    # 积分命令别名
    points_alias: Mapped[str] = mapped_column(String(32), default="积分")  # 查询积分别名
    points_rank_alias: Mapped[str] = mapped_column(String(32), default="积分排行")  # 积分排行别名

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


class UserDailyStats(Base):
    """用户每日统计：用于发言积分、邀请积分的每日上限控制"""
    __tablename__ = "user_daily_stats"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "stat_date", name="uq_user_daily_stat"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    stat_date: Mapped[dt.date] = mapped_column(default=lambda: dt.datetime.now(dt.UTC).date(), index=True)

    # 发言积分相关
    message_points_earned: Mapped[int] = mapped_column(Integer, default=0)  # 今日发言已获得积分

    # 邀请积分相关
    invite_points_earned: Mapped[int] = mapped_column(Integer, default=0)  # 今日邀请已获得积分
    invites_count: Mapped[int] = mapped_column(Integer, default=0)  # 今日邀请人数

    # 连续签到
    consecutive_sign_days: Mapped[int] = mapped_column(Integer, default=0)  # 连续签到天数

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


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
    """广告活动"""
    __tablename__ = "ad_campaigns"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    image_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 图片文件ID（Telegram）
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # 图片URL
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否包含图片
    schedule_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 定时推送时间
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 推送频次: once/daily/weekly/monthly
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 上次发送时间
    send_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # 发送锁定（防重机制）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 高级推送配置（支持自定义间隔和次数）
    start_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始推送时间"
    )
    interval_hours: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="推送间隔（小时），如24表示每24小时推送一次"
    )
    max_send_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="最大推送次数，null表示无限制"
    )
    send_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="已推送次数"
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


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
    points_reward: Mapped[int] = mapped_column(Integer, default=0)  # 积分奖励
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
    repeat_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否重复发送
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


class InviteTracking(Base):
    """邀请追踪：记录谁邀请谁加入了群组"""
    __tablename__ = "invite_tracking"
    __table_args__ = (
        UniqueConstraint("chat_id", "invited_user_id", name="uq_invite_tracking"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    inviter_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True, index=True)  # 邀请人
    invited_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)  # 被邀请人
    invite_link_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bot.invite_links.id", ondelete="SET NULL"), nullable=True)  # 使用的邀请链接
    points_awarded: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已发放积分
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))  # 加入时间
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


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
    points_required: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 参与所需积分（null=无限制）
    deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 截止时间（null=无限制）
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 接龙消息ID（用于更新）
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    # 关系：参与记录
    entries_rel: Mapped[list["SolitaireEntry"]] = relationship(
        "SolitaireEntry",
        back_populates="solitaire",
        cascade="all, delete-orphan",
        lazy="select"  # 使用 select 策略，需要在查询时显式预加载
    )


class SolitaireEntry(Base):
    """接龙参与记录"""
    __tablename__ = "solitaire_entries"
    __table_args__ = (
        UniqueConstraint("solitaire_id", "user_id", name="uq_solitaire_entries"),
        {"schema": "bot"}
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    solitaire_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.solitaires.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 用户名（用于显示）
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 参与内容
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))  # 参与时间
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 更新时间
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))

    # 关系：接龙
    solitaire: Mapped["Solitaire"] = relationship("Solitaire", back_populates="entries_rel")




