from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import BannedWord
from backend.platform.db.schema.models.enums import BannedWordMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult

WordLoader = Callable[[AsyncSession, int], Awaitable[BannedWord | None]]
ScopedWordLoader = Callable[[AsyncSession, int, int], Awaitable[BannedWord | None]]
ContentWordLoader = Callable[[AsyncSession, int, str], Awaitable[BannedWord | None]]


async def create_banned_word_impl(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    word: str,
    *,
    match_type: str,
    action: str,
    mute_duration: int,
    notify: bool,
    notify_message: str | None,
    case_sensitive: bool,
    get_banned_word_by_content_func: ContentWordLoader,
) -> CreateResult:
    if not word or not word.strip():
        return CreateResult(success=False, reason="invalid_word")

    word = word.strip()
    existing = await get_banned_word_by_content_func(session, chat_id, word)
    if existing:
        return CreateResult(success=False, reason="duplicate")

    if match_type not in [item.value for item in BannedWordMatchType]:
        return CreateResult(success=False, reason="invalid_match_type")
    if action not in ["delete", "mute", "ban"]:
        return CreateResult(success=False, reason="invalid_action")
    if match_type == BannedWordMatchType.regex.value:
        try:
            re.compile(word)
        except re.error:
            return CreateResult(success=False, reason="invalid_word")

    banned_word = BannedWord(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        word=word,
        match_type=match_type,
        action=action,
        mute_duration=mute_duration,
        notify=notify,
        notify_message=notify_message,
        case_sensitive=case_sensitive,
    )
    session.add(banned_word)
    await session.flush()
    return CreateResult(success=True, reason="ok", entity=banned_word, entity_id=banned_word.id)


async def toggle_banned_word_impl(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None,
    get_banned_word_func: WordLoader,
    get_banned_word_in_chat_func: ScopedWordLoader,
) -> bool:
    word = await (
        get_banned_word_in_chat_func(session, chat_id, word_id)
        if chat_id is not None
        else get_banned_word_func(session, word_id)
    )
    if not word:
        return False
    await ServiceBase._update_entity(session, word, {"is_active": not word.is_active})
    return True


async def delete_banned_word_impl(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None,
    get_banned_word_func: WordLoader,
    get_banned_word_in_chat_func: ScopedWordLoader,
) -> bool:
    word = await (
        get_banned_word_in_chat_func(session, chat_id, word_id)
        if chat_id is not None
        else get_banned_word_func(session, word_id)
    )
    if not word:
        return False
    await ServiceBase._delete_entity(session, word)
    return True
