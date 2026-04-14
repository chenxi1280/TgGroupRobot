from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import BannedWord
from backend.shared.services.base import ServiceBase


async def get_banned_word(session: AsyncSession, word_id: int) -> BannedWord | None:
    return await ServiceBase._get_by_id(session, BannedWord, word_id)


async def get_banned_word_in_chat(
    session: AsyncSession,
    chat_id: int,
    word_id: int,
) -> BannedWord | None:
    return await ServiceBase._get_by_filters(
        session,
        BannedWord,
        {"id": word_id, "chat_id": chat_id},
    )


async def get_banned_word_by_content(
    session: AsyncSession,
    chat_id: int,
    word: str,
) -> BannedWord | None:
    return await ServiceBase._get_by_filters(
        session,
        BannedWord,
        {"chat_id": chat_id, "word": word},
    )


async def get_chat_banned_words(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[BannedWord]:
    return await ServiceBase._get_list(
        session,
        BannedWord,
        filters={"chat_id": chat_id},
        active_only=active_only,
        order_by="created_at",
        descending=True,
    )


async def get_trigger_stats(
    session: AsyncSession,
    chat_id: int,
) -> int:
    words = await ServiceBase._get_list(
        session,
        BannedWord,
        filters={"chat_id": chat_id},
    )
    return sum(word.trigger_count for word in words)
