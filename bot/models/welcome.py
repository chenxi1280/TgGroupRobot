from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class WelcomeMessage(Base):
    __tablename__ = "welcome_messages"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128), default="待配置")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_mode: Mapped[str] = mapped_column(String(32), default="after_verify")
    cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text_content: Mapped[str] = mapped_column(Text, default="{member}，欢迎加入{group}。")
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    delete_mode: Mapped[str] = mapped_column(String(32), default="seconds")
    delete_delay_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, default=15)
    last_sent_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )
