from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base


class GroupAlliance(Base):
    __tablename__ = "group_alliances"
    __table_args__ = {"schema": "bot"}

    alliance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    owner_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
    )
    invite_code_hash: Mapped[str] = mapped_column(String(128))
    invite_code_expire_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GroupAllianceMember(Base):
    __tablename__ = "group_alliance_members"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_group_alliance_member_chat"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bot.group_alliances.alliance_id", ondelete="CASCADE"),
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
    )
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )
    status: Mapped[str] = mapped_column(String(16), default="active")


class GroupAllianceSetting(Base):
    __tablename__ = "group_alliance_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    alliance_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bot.group_alliances.alliance_id", ondelete="CASCADE"),
        index=True,
    )
    joint_ban_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GroupAllianceBanPool(Base):
    __tablename__ = "group_alliance_ban_pool"
    __table_args__ = (
        UniqueConstraint("alliance_id", "target_user_id", name="uq_group_alliance_ban_pool"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bot.group_alliances.alliance_id", ondelete="CASCADE"),
        index=True,
    )
    target_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="CASCADE"),
    )
    source_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
    )
    source_operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )


class GroupAllianceAudit(Base):
    __tablename__ = "group_alliance_audit"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    alliance_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("bot.group_alliances.alliance_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64))
    operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[str] = mapped_column(String(16), default="success")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )


class GarageForwardSetting(Base):
    __tablename__ = "garage_forward_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_mode: Mapped[str] = mapped_column(String(16), default="all")
    keyword_rules: Mapped[list] = mapped_column(JSONB, default=list)
    button_template_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    button_template: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GarageForwardSource(Base):
    __tablename__ = "garage_forward_sources"
    __table_args__ = (
        UniqueConstraint("chat_id", "source_channel_id", name="uq_garage_forward_source_chat_channel"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    source_channel_id: Mapped[int] = mapped_column(BigInteger)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="最近处理的源频道消息 ID 游标，用于观测缺口与未来回扫能力",
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )


class GarageForwardMessageMap(Base):
    __tablename__ = "garage_forward_message_map"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "source_channel_id",
            "source_message_id",
            name="uq_garage_forward_message_map",
        ),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    source_channel_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    target_message_id: Mapped[int] = mapped_column(BigInteger)
    forwarded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )


class GarageForwardAuditLog(Base):
    __tablename__ = "garage_forward_audit_logs"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    source_channel_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )


class GarageForwardRetryQueue(Base):
    """车库转发的持久化执行记录。"""

    __tablename__ = "garage_forward_retry_queue"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "source_channel_id",
            "source_message_id",
            name="uq_garage_forward_retry_event",
        ),
        Index(
            "ix_garage_forward_retry_due",
            "status",
            "next_retry_at",
            "lease_until",
        ),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    source_channel_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    message_map_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("bot.garage_forward_message_map.id", ondelete="SET NULL"),
        nullable=True,
    )
    reply_markup_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="已重试次数")
    max_retries: Mapped[int] = mapped_column(Integer, default=3, comment="最大重试次数")
    next_retry_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        nullable=True,
        comment="下次重试时间，按指数退避计算",
    )
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近一次失败原因")
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )
