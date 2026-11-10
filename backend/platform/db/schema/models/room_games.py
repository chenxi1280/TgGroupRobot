from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base


class RoomGame(Base):
    __tablename__ = "room_games"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id"), index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    game: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    unit: Mapped[int] = mapped_column(Integer)
    fee: Mapped[int] = mapped_column(Integer)
    hand_limit: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=0)
    deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    seats: Mapped[list] = mapped_column(JSONB)
    options: Mapped[dict] = mapped_column(JSONB)
    hand: Mapped[dict] = mapped_column(JSONB)
    history: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class PlatformGameFee(Base):
    __tablename__ = "platform_game_fees"
    __table_args__ = {"schema": "bot"}

    game: Mapped[str] = mapped_column(String(16), primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    charged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
