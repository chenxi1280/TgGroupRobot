from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, TgChat


async def ensure_chat(session: AsyncSession, chat_id: int, chat_type: str, title: str | None) -> TgChat:
    res = await session.execute(select(TgChat).where(TgChat.id == chat_id))
    chat = res.scalar_one_or_none()
    if chat is None:
        chat = TgChat(id=chat_id, type=chat_type, title=title)
        session.add(chat)
        await session.flush()
    else:
        chat.title = title
        chat.type = chat_type
        chat.updated_at = dt.datetime.now(dt.UTC)

    res2 = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = res2.scalar_one_or_none()
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return chat


async def get_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    res = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = res.scalar_one()
    return settings



