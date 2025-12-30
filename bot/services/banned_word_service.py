from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import BannedWord
from bot.models.enums import BannedWordMatchType


@dataclass
class CreateResult:
    """创建违禁词结果"""
    success: bool
    reason: Literal[
        "ok",
        "invalid_word",
        "invalid_match_type",
        "invalid_action",
        "duplicate",
    ]
    word: BannedWord | None = None


@dataclass
class MatchResult:
    """匹配结果"""
    matched: bool
    word: BannedWord | None = None


async def create_banned_word(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    word: str,
    match_type: str = BannedWordMatchType.contains.value,
    action: str = "delete",
    mute_duration: int = 60,
    notify: bool = True,
    notify_message: str | None = None,
    case_sensitive: bool = False,
) -> CreateResult:
    """创建违禁词"""
    # 验证违禁词
    if not word or not word.strip():
        return CreateResult(success=False, reason="invalid_word")

    word = word.strip()

    # 检查是否已存在
    existing = await get_banned_word_by_content(session, chat_id, word)
    if existing:
        return CreateResult(success=False, reason="duplicate")

    # 验证匹配类型
    valid_types = [e.value for e in BannedWordMatchType]
    if match_type not in valid_types:
        return CreateResult(success=False, reason="invalid_match_type")

    # 验证动作
    valid_actions = ["delete", "mute", "ban"]
    if action not in valid_actions:
        return CreateResult(success=False, reason="invalid_action")

    # 如果是正则表达式，验证格式
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
    return CreateResult(success=True, reason="ok", word=banned_word)


async def get_banned_word(session: AsyncSession, word_id: int) -> BannedWord | None:
    """获取违禁词"""
    stmt = select(BannedWord).where(BannedWord.id == word_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_banned_word_by_content(
    session: AsyncSession,
    chat_id: int,
    word: str,
) -> BannedWord | None:
    """根据内容获取违禁词"""
    stmt = select(BannedWord).where(
        BannedWord.chat_id == chat_id,
        BannedWord.word == word,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_chat_banned_words(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[BannedWord]:
    """获取群组的违禁词列表"""
    stmt = select(BannedWord).where(BannedWord.chat_id == chat_id)
    if active_only:
        stmt = stmt.where(BannedWord.is_active == True)
    stmt = stmt.order_by(BannedWord.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def toggle_banned_word(
    session: AsyncSession,
    word_id: int,
) -> bool:
    """切换违禁词激活状态"""
    word = await get_banned_word(session, word_id)
    if not word:
        return False
    word.is_active = not word.is_active
    return True


async def delete_banned_word(
    session: AsyncSession,
    word_id: int,
) -> bool:
    """删除违禁词"""
    word = await get_banned_word(session, word_id)
    if not word:
        return False
    await session.delete(word)
    return True


async def match_banned_words(
    session: AsyncSession,
    chat_id: int,
    text: str,
) -> list[BannedWord]:
    """匹配违禁词，返回所有匹配的违禁词"""
    words = await get_chat_banned_words(session, chat_id, active_only=True)

    matched = []
    for word in words:
        if _match_word(word, text):
            word.trigger_count += 1
            matched.append(word)

    return matched


def _match_word(banned_word: BannedWord, text: str) -> bool:
    """检查文本是否匹配违禁词"""
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


async def get_trigger_stats(
    session: AsyncSession,
    chat_id: int,
) -> int:
    """获取群组违禁词总触发次数"""
    stmt = select(BannedWord).where(BannedWord.chat_id == chat_id)
    result = await session.execute(stmt)
    words = result.scalars().all()
    return sum(word.trigger_count for word in words)
