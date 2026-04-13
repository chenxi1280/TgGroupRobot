from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


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
