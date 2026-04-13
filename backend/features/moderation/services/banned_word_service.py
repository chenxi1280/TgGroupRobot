from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import BannedWord
from backend.platform.db.schema.models.enums import BannedWordMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult, MatchResult


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
    """
    创建违禁词

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        created_by_user_id: 创建者用户 ID
        word: 违禁词内容
        match_type: 匹配类型
        action: 处罚动作
        mute_duration: 禁言时长（秒）
        notify: 是否通知
        notify_message: 自定义通知消息
        case_sensitive: 是否区分大小写

    Returns:
        CreateResult: 创建结果
    """
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
    return CreateResult(success=True, reason="ok", entity=banned_word, entity_id=banned_word.id)


async def get_banned_word(session: AsyncSession, word_id: int) -> BannedWord | None:
    """
    获取违禁词

    Args:
        session: 数据库会话
        word_id: 违禁词 ID

    Returns:
        BannedWord: 违禁词对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_id(session, BannedWord, word_id)


async def get_banned_word_in_chat(
    session: AsyncSession,
    chat_id: int,
    word_id: int,
) -> BannedWord | None:
    """按群组作用域获取违禁词，避免跨群访问。"""
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
    """
    根据内容获取违禁词

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        word: 违禁词内容

    Returns:
        BannedWord: 违禁词对象，如果不存在则返回 None
    """
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
    """
    获取群组的违禁词列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        active_only: 是否只返回激活的违禁词

    Returns:
        违禁词列表
    """
    return await ServiceBase._get_list(
        session,
        BannedWord,
        filters={"chat_id": chat_id},
        active_only=active_only,
        order_by="created_at",
        descending=True,
    )


async def toggle_banned_word(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    """
    切换违禁词激活状态

    Args:
        session: 数据库会话
        word_id: 违禁词 ID

    Returns:
        是否切换成功
    """
    word = await (
        get_banned_word_in_chat(session, chat_id, word_id)
        if chat_id is not None
        else get_banned_word(session, word_id)
    )
    if not word:
        return False
    await ServiceBase._update_entity(
        session,
        word,
        {"is_active": not word.is_active},
    )
    return True


async def delete_banned_word(
    session: AsyncSession,
    word_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    """
    删除违禁词

    Args:
        session: 数据库会话
        word_id: 违禁词 ID

    Returns:
        是否删除成功
    """
    word = await (
        get_banned_word_in_chat(session, chat_id, word_id)
        if chat_id is not None
        else get_banned_word(session, word_id)
    )
    if not word:
        return False
    await ServiceBase._delete_entity(session, word)
    return True


async def match_banned_words(
    session: AsyncSession,
    chat_id: int,
    text: str,
) -> list[BannedWord]:
    """
    匹配违禁词，返回所有匹配的违禁词

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        text: 待检查的文本

    Returns:
        匹配的违禁词列表
    """
    words = await get_chat_banned_words(session, chat_id, active_only=True)

    matched = []
    for word in words:
        if _match_word(word, text):
            await ServiceBase._update_entity(
                session,
                word,
                {"trigger_count": word.trigger_count + 1},
            )
            matched.append(word)

    return matched


def _match_word(banned_word: BannedWord, text: str) -> bool:
    """
    检查文本是否匹配违禁词

    Args:
        banned_word: 违禁词对象
        text: 待检查的文本

    Returns:
        是否匹配
    """
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
    """
    获取群组违禁词总触发次数

    Args:
        session: 数据库会话
        chat_id: 群组 ID

    Returns:
        总触发次数
    """
    words = await ServiceBase._get_list(
        session,
        BannedWord,
        filters={"chat_id": chat_id},
    )
    return sum(word.trigger_count for word in words)
