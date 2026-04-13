from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base


class BottomButtonSetting(Base):
    __tablename__ = "bottom_button_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    header_text: Mapped[str] = mapped_column(Text, default="⌨️ 底部按钮已生成，点击下方按钮即可使用。")
    generated_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    repeat_generate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    last_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class BottomButtonLayout(Base):
    __tablename__ = "bottom_button_layouts"
    __table_args__ = (
        UniqueConstraint("chat_id", "row_no", "col_no", name="uq_bottom_button_layout_chat_pos"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    col_no: Mapped[int] = mapped_column(Integer, nullable=False)
    button_text: Mapped[str] = mapped_column(String(32), default="按钮")
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_mode: Mapped[str] = mapped_column(String(16), default="send")
    sort_key: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )
