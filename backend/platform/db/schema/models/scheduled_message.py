from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base


class ScheduledMessageTask(Base):
    """定时消息任务表：支持灵活的定时消息发送配置"""
    __tablename__ = "scheduled_message_tasks"
    __table_args__ = {"schema": "bot"}

    # 主键和关联
    task_id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)  # UUID 主键
    short_id: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)  # 短 ID（用于 callback_data）
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)

    # 基础信息
    title: Mapped[str] = mapped_column(String(128))  # 任务标题
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # 是否启用

    # 重复配置
    repeat_interval_min: Mapped[int] = mapped_column(Integer, default=60)  # 重复间隔（分钟）：10/15/20/30/60/120/180/240/360/480/720/1440
    day_start_hour: Mapped[int] = mapped_column(Integer, default=0)  # 每日开始小时（0-23）
    day_end_hour: Mapped[int] = mapped_column(Integer, default=23)  # 每日结束小时（0-23）

    # 时间范围（Unix 时间戳）
    start_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 开始时间（Unix 时间戳）
    end_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 终止时间（Unix 时间戳）

    # 内容配置
    text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 消息文本
    parse_mode: Mapped[str] = mapped_column(String(16), default="HTML")  # 解析模式：HTML/Markdown/None
    media_type: Mapped[str] = mapped_column(String(16), default="none")  # 媒体类型：photo/video/sticker/animation/document/none
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 媒体文件 ID（Telegram）
    buttons: Mapped[list] = mapped_column(JSONB, default=list)  # 按钮配置（JSONB）：[[{text,url},...],...]

    # 发送选项
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=True)  # 发送前删除上一条
    pin_message: Mapped[bool] = mapped_column(Boolean, default=False)  # 置顶消息

    # 执行状态
    last_sent_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 上次发送的消息 ID
    next_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)  # 下次执行时间（Unix 时间戳）

    # 时间戳
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class ScheduledMessageLog(Base):
    """定时消息 occurrence 与发送审计记录。"""

    __tablename__ = "scheduled_message_logs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_sml_run_key"),
        Index("ix_sml_due", "status", "next_retry_at", "lease_until"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bot.scheduled_message_tasks.task_id", ondelete="CASCADE"),
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger)
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_for: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    content_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
