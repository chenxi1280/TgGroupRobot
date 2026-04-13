from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import SubscriptionStatus


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
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


class RenewalCardKey(Base):
    __tablename__ = "renewal_card_keys"
    __table_args__ = (
        UniqueConstraint("card_key_hash", name="uq_renewal_card_key_hash"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_key_hash: Mapped[str] = mapped_column(String(128), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    used_by_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_chats.id", ondelete="SET NULL"),
        nullable=True,
    )
    used_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class RenewalAuditLog(Base):
    __tablename__ = "renewal_audit_logs"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
