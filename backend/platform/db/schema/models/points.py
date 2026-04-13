from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import PointsTxnType


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
    __tablename__ = "user_daily_stats"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "stat_date", name="uq_user_daily_stat"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    stat_date: Mapped[dt.date] = mapped_column(default=lambda: dt.datetime.now(dt.UTC).date(), index=True)
    message_points_earned: Mapped[int] = mapped_column(Integer, default=0)
    invite_points_earned: Mapped[int] = mapped_column(Integer, default=0)
    invites_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_sign_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CustomPointType(Base):
    __tablename__ = "custom_point_types"
    __table_args__ = (
        UniqueConstraint("chat_id", "type_no", name="uq_custom_point_type_chat_no"),
        UniqueConstraint("chat_id", "name", name="uq_custom_point_type_chat_name"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    type_no: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    rank_command: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CustomPointAccount(Base):
    __tablename__ = "custom_point_accounts"
    __table_args__ = (
        UniqueConstraint("chat_id", "type_id", "user_id", name="uq_custom_point_account_chat_type_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    type_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.custom_point_types.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CustomPointLedger(Base):
    __tablename__ = "custom_point_ledger"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    type_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.custom_point_types.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)


class PointsLevelSetting(Base):
    __tablename__ = "points_level_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_teacher_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsLevel(Base):
    __tablename__ = "points_levels"
    __table_args__ = (
        UniqueConstraint("chat_id", "level_no", name="uq_points_level_chat_no"),
        UniqueConstraint("chat_id", "point_threshold", name="uq_points_level_chat_threshold"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    level_no: Mapped[int] = mapped_column(Integer, index=True)
    level_name: Mapped[str] = mapped_column(String(64))
    point_threshold: Mapped[int] = mapped_column(Integer, index=True)
    allow_text: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_photo: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_video: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_sticker: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_document: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_mention: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsMallSetting(Base):
    __tablename__ = "points_mall_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_command: Mapped[str] = mapped_column(String(32), default="积分商城")
    auto_unlist_when_out_of_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    redeem_notice_delete_seconds: Mapped[int] = mapped_column(Integer, default=60)
    cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsMallProduct(Base):
    __tablename__ = "points_mall_products"
    __table_args__ = {"schema": "bot"}

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    price_points: Mapped[int] = mapped_column(Integer)
    stock_total: Mapped[int] = mapped_column(Integer, default=0)
    stock_left: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="on_sale", index=True)
    cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    limit_per_user: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fulfiller_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_weight: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsMallOrder(Base):
    __tablename__ = "points_mall_orders"
    __table_args__ = {"schema": "bot"}

    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.points_mall_products.product_id", ondelete="CASCADE"), index=True)
    buyer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    price_points: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    order_status: Mapped[str] = mapped_column(String(16), default="created", index=True)
    operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class PointsMallOrderLog(Base):
    __tablename__ = "points_mall_order_logs"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.points_mall_orders.order_id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
