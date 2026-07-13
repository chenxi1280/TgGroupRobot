from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import InviteLinkStatus, ScheduleType


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    image_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="开始推送时间")
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="推送间隔（小时），如24表示每24小时推送一次")
    max_send_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最大推送次数，null表示无限制")
    send_count: Mapped[int] = mapped_column(Integer, default=0, comment="已推送次数")
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=1, index=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="结束时间")
    last_sent_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="上次发送的消息 ID")
    last_sent_cycle_no: Mapped[int] = mapped_column(Integer, default=0, comment="上次发送所在轮次")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AdRotationRule(Base):
    __tablename__ = "ad_rotation_rules"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=7200)
    mode: Mapped[str] = mapped_column(String(16), default="send")
    delete_policy: Mapped[str] = mapped_column(String(32), default="delete_prev_cycle")
    delete_delay_seconds: Mapped[int] = mapped_column(Integer, default=60)
    unpin_previous: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    current_order_cursor: Mapped[int] = mapped_column(Integer, default=1)
    last_sent_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bot.ad_campaigns.id", ondelete="SET NULL"), nullable=True)
    last_sent_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_pinned_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_campaign_ids: Mapped[list] = mapped_column(JSONB, default=list, comment="置顶轮播池，空表示全部参与")
    exclude_campaign_ids: Mapped[list] = mapped_column(JSONB, default=list, comment="排除的条目 ID 列表")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AdRotationHistory(Base):
    """轮播派发 occurrence、状态与操作审计。"""

    __tablename__ = "ad_rotation_history"
    __table_args__ = (
        UniqueConstraint("dispatch_key", name="uq_ad_rotation_history_dispatch_key"),
        Index("ix_ad_rotation_history_due", "status", "next_retry_at", "lease_until"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.ad_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    dispatch_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_for: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    content_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay_of_history_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replay_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    replay_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pinned_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_no: Mapped[int] = mapped_column(Integer, default=0, comment="该条目累计发送轮次")
    sort_order_snapshot: Mapped[int] = mapped_column(Integer, default=1, comment="发送时的 sort_order 快照")
    title_snapshot: Mapped[str] = mapped_column(String(128), default="", comment="发送时的标题快照")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ScheduledMessage(Base):
    __tablename__ = "scheduled_messages"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String(32), default=ScheduleType.none.value, index=True)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_send_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_count: Mapped[int] = mapped_column(Integer, default=0)
    repeat_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class InviteLink(Base):
    __tablename__ = "invite_links"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    invite_link: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=InviteLinkStatus.active.value)
    member_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    expire_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creates_join_request: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class InviteTracking(Base):
    __tablename__ = "invite_tracking"
    __table_args__ = (
        UniqueConstraint("chat_id", "invited_user_id", name="uq_invite_tracking"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    inviter_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True, index=True)
    invited_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    invite_link_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bot.invite_links.id", ondelete="SET NULL"), nullable=True)
    points_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
