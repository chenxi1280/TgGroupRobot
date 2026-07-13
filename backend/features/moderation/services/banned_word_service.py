from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.moderation.services.banned_word_matching import match_banned_words_impl, match_word
from backend.features.moderation.services.banned_word_mutations import (
    create_banned_word_impl,
    delete_banned_word_impl,
    toggle_banned_word_impl,
)
from backend.features.moderation.services.banned_word_queries import (
    get_banned_word as _get_banned_word,
)
from backend.features.moderation.services.banned_word_queries import (
    get_banned_word_by_content as _get_banned_word_by_content,
)
from backend.features.moderation.services.banned_word_queries import (
    get_banned_word_in_chat as _get_banned_word_in_chat,
)
from backend.features.moderation.services.banned_word_queries import (
    get_chat_banned_words as _get_chat_banned_words,
)
from backend.features.moderation.services.banned_word_queries import (
    get_trigger_stats as _get_trigger_stats,
)
from backend.platform.db.schema.models.core import BannedWord
from backend.platform.db.schema.models.enums import BannedWordMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult


async def create_banned_word(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    *, word: str,
    match_type: str = BannedWordMatchType.contains.value,
    action: str = "delete",
    mute_duration: int = 60,
    notify: bool = True,
    notify_message: str | None = None,
    case_sensitive: bool = False,
) -> CreateResult:
    return await create_banned_word_impl(
        session,
        chat_id,
        created_by_user_id,
        word=word,
        match_type=match_type,
        action=action,
        mute_duration=mute_duration,
        notify=notify,
        notify_message=notify_message,
        case_sensitive=case_sensitive,
        get_banned_word_by_content_func=get_banned_word_by_content,
    )


async def get_banned_word(session: AsyncSession, word_id: int) -> BannedWord | None:
    return await _get_banned_word(session, word_id)


async def get_banned_word_in_chat(
    session: AsyncSession,
    chat_id: int,
    word_id: int,
) -> BannedWord | None:
    return await _get_banned_word_in_chat(session, chat_id, word_id)


async def get_banned_word_by_content(
    session: AsyncSession,
    chat_id: int,
    word: str,
) -> BannedWord | None:
    return await _get_banned_word_by_content(session, chat_id, word)


async def get_chat_banned_words(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[BannedWord]:
    return await _get_chat_banned_words(session, chat_id, active_only=active_only)


async def toggle_banned_word(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await toggle_banned_word_impl(
        session,
        word_id,
        chat_id=chat_id,
        get_banned_word_func=get_banned_word,
        get_banned_word_in_chat_func=get_banned_word_in_chat,
    )


async def delete_banned_word(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await delete_banned_word_impl(
        session,
        word_id,
        chat_id=chat_id,
        get_banned_word_func=get_banned_word,
        get_banned_word_in_chat_func=get_banned_word_in_chat,
    )


async def match_banned_words(
    session: AsyncSession,
    chat_id: int,
    text: str,
) -> list[BannedWord]:
    return await match_banned_words_impl(
        session,
        chat_id,
        text,
        get_chat_banned_words_func=get_chat_banned_words,
    )


def _match_word(banned_word: BannedWord, text: str) -> bool:
    return match_word(banned_word, text)


async def get_trigger_stats(
    session: AsyncSession,
    chat_id: int,
) -> int:
    return await _get_trigger_stats(session, chat_id)
