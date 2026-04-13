from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import LotteryDrawMode, SolitaireStatus


class Lottery(Base):
    __tablename__ = "lotteries"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(128), default="通用抽奖")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lottery_type: Mapped[str] = mapped_column(String(16), default="common")
    draw_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    prizes: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    draw_mode: Mapped[str] = mapped_column(String(16), default=LotteryDrawMode.manual.value)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualification_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    min_points: Mapped[int] = mapped_column(Integer, default=0)
    max_participants: Mapped[int] = mapped_column(Integer, default=0)
    participation_cost: Mapped[int] = mapped_column(Integer, default=0)
    join_start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    join_end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requirement_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    drawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LotteryParticipant(Base):
    __tablename__ = "lottery_participants"
    __table_args__ = (
        UniqueConstraint("lottery_id", "user_id", name="uq_lottery_participant"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lottery_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.lotteries.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class LotteryWinner(Base):
    __tablename__ = "lottery_winners"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lottery_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.lotteries.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    prize_name: Mapped[str] = mapped_column(String(255))
    prize_index: Mapped[int] = mapped_column(Integer)
    points_reward: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class Solitaire(Base):
    __tablename__ = "solitaires"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=SolitaireStatus.active.value)
    max_participants: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    entries_rel: Mapped[list["SolitaireEntry"]] = relationship(
        "SolitaireEntry",
        back_populates="solitaire",
        cascade="all, delete-orphan",
        lazy="select",
    )


class SolitaireEntry(Base):
    __tablename__ = "solitaire_entries"
    __table_args__ = (
        UniqueConstraint("solitaire_id", "user_id", name="uq_solitaire_entries"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    solitaire_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.solitaires.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))

    solitaire: Mapped["Solitaire"] = relationship("Solitaire", back_populates="entries_rel")
