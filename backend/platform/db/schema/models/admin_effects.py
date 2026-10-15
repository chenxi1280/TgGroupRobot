"""Durable generic administration side effects and tag ownership."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from backend.platform.db.runtime.base import Base


class AdminEffect(Base):
    __tablename__ = 'admin_effects'
    __table_args__ = (Index('ix_admin_effect_due', 'status', 'next_run_at'), {'schema': 'bot'})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    effect_key: Mapped[str] = mapped_column(String(128), unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LevelTagState(Base):
    __tablename__ = 'level_tag_states'
    __table_args__ = {'schema': 'bot'}
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    applied_tag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    desired_tag: Mapped[str] = mapped_column(String(16), default='')
    status: Mapped[str] = mapped_column(String(32), default='pending')
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.min.replace(tzinfo=dt.UTC))


class NoticeConsent(Base):
    __tablename__ = 'notice_consents'
    __table_args__ = {'schema': 'bot'}
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ad_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
