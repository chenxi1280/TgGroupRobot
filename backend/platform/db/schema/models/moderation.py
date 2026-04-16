from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import (
    AutoReplyMatchType,
    BannedWordMatchType,
    ModerationAction,
    VerificationMode,
)


class ModerationViolation(Base):
    __tablename__ = "moderation_violations"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(32), default=ModerationAction.delete.value)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class ModerationWarning(Base):
    __tablename__ = "moderation_warnings"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_moderation_warnings_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    last_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


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
    verification_type: Mapped[str] = mapped_column(String(16), default=VerificationMode.button.value)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeout_handled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class AutoReplyRule(Base):
    __tablename__ = "auto_reply_rules"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reply_content: Mapped[str] = mapped_column(Text)
    cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    match_type: Mapped[str] = mapped_column(String(16), default=AutoReplyMatchType.contains.value)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    delete_source: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_reply_delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_after_match: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class BannedWord(Base):
    __tablename__ = "banned_words"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    word: Mapped[str] = mapped_column(String(255), index=True)
    match_type: Mapped[str] = mapped_column(String(16), default=BannedWordMatchType.contains.value)
    action: Mapped[str] = mapped_column(String(16), default="delete")
    mute_duration: Mapped[int] = mapped_column(Integer, default=60)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )
