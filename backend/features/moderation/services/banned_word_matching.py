from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import BannedWord
from backend.platform.db.schema.models.enums import BannedWordMatchType
from backend.shared.services.base import ServiceBase

WordListLoader = Callable[[AsyncSession, int, bool], Awaitable[list[BannedWord]]]


def match_word(banned_word: BannedWord, text: str) -> bool:
    word = banned_word.word
    if not banned_word.case_sensitive:
        text = text.lower()
        word = word.lower()

    match banned_word.match_type:
        case BannedWordMatchType.exact.value:
            return text == word
        case BannedWordMatchType.contains.value:
            return word in text
        case BannedWordMatchType.regex.value:
            try:
                return bool(re.search(banned_word.word, text))
            except re.error:
                return False
    return False


async def match_banned_words_impl(
    session: AsyncSession,
    chat_id: int,
    text: str,
    *,
    get_chat_banned_words_func: WordListLoader,
) -> list[BannedWord]:
    words = await get_chat_banned_words_func(session, chat_id, active_only=True)
    matched: list[BannedWord] = []
    for word in words:
        if match_word(word, text):
            await ServiceBase._update_entity(
                session,
                word,
                {"trigger_count": word.trigger_count + 1},
            )
            matched.append(word)
    return matched
