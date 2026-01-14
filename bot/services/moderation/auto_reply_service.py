from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import AutoReplyRule
from bot.models.enums import AutoReplyMatchType
from bot.services.base import ServiceBase
from bot.services.shared.result import CreateResult, MatchResult


async def create_auto_reply_rule(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    keywords: list[str],
    reply_content: str,
    match_type: str = AutoReplyMatchType.contains.value,
    case_sensitive: bool = False,
) -> CreateResult:
    """
    创建自动回复规则

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        created_by_user_id: 创建者用户 ID
        keywords: 关键词列表
        reply_content: 回复内容
        match_type: 匹配类型
        case_sensitive: 是否区分大小写

    Returns:
        CreateResult: 创建结果
    """
    # 验证关键词
    if not keywords or not all(k.strip() for k in keywords):
        return CreateResult(success=False, reason="invalid_keywords")

    # 验证回复内容
    if not reply_content or not reply_content.strip():
        return CreateResult(success=False, reason="invalid_reply")

    # 验证匹配类型
    valid_types = [e.value for e in AutoReplyMatchType]
    if match_type not in valid_types:
        return CreateResult(success=False, reason="invalid_match_type")

    # 如果是正则表达式，验证格式
    if match_type == AutoReplyMatchType.regex.value:
        for keyword in keywords:
            try:
                re.compile(keyword)
            except re.error:
                return CreateResult(success=False, reason="invalid_keywords")

    rule = AutoReplyRule(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        keywords=[k.strip() for k in keywords],
        reply_content=reply_content,
        match_type=match_type,
        case_sensitive=case_sensitive,
    )
    session.add(rule)
    await session.flush()
    return CreateResult(success=True, reason="ok", entity=rule, entity_id=rule.id)


async def get_auto_reply_rule(session: AsyncSession, rule_id: int) -> AutoReplyRule | None:
    """
    获取自动回复规则

    Args:
        session: 数据库会话
        rule_id: 规则 ID

    Returns:
        AutoReplyRule: 规则对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_id(session, AutoReplyRule, rule_id)


async def get_chat_auto_reply_rules(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[AutoReplyRule]:
    """
    获取群组的自动回复规则列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        active_only: 是否只返回激活的规则

    Returns:
        自动回复规则列表
    """
    return await ServiceBase._get_list(
        session,
        AutoReplyRule,
        filters={"chat_id": chat_id},
        active_only=active_only,
        order_by="created_at",
        descending=True,
    )


async def toggle_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
) -> bool:
    """
    切换自动回复规则激活状态

    Args:
        session: 数据库会话
        rule_id: 规则 ID

    Returns:
        是否切换成功
    """
    rule = await get_auto_reply_rule(session, rule_id)
    if not rule:
        return False
    await ServiceBase._update_entity(
        session,
        rule,
        {"is_active": not rule.is_active},
    )
    return True


async def delete_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
) -> bool:
    """
    删除自动回复规则

    Args:
        session: 数据库会话
        rule_id: 规则 ID

    Returns:
        是否删除成功
    """
    rule = await get_auto_reply_rule(session, rule_id)
    if not rule:
        return False
    await ServiceBase._delete_entity(session, rule)
    return True


async def match_auto_reply(
    session: AsyncSession,
    chat_id: int,
    message_text: str,
) -> MatchResult:
    """
    匹配自动回复规则

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        message_text: 消息文本

    Returns:
        MatchResult: 匹配结果
    """
    rules = await get_chat_auto_reply_rules(session, chat_id, active_only=True)

    for rule in rules:
        if _match_rule(rule, message_text):
            # 增加匹配计数
            await ServiceBase._update_entity(
                session,
                rule,
                {"match_count": rule.match_count + 1},
            )
            return MatchResult(
                success=True,
                reason="matched",
                rule=rule,
                reply_content=rule.reply_content,
            )

    return MatchResult(
        success=False,
        reason="no_match",
        rule=None,
        reply_content=None,
    )


def _match_rule(rule: AutoReplyRule, text: str) -> bool:
    """
    检查消息是否匹配规则

    Args:
        rule: 自动回复规则
        text: 消息文本

    Returns:
        是否匹配
    """
    if not rule.case_sensitive:
        text = text.lower()

    for keyword in rule.keywords:
        kw = keyword if rule.case_sensitive else keyword.lower()

        match rule.match_type:
            case AutoReplyMatchType.exact.value:
                if text == kw:
                    return True
            case AutoReplyMatchType.contains.value:
                if kw in text:
                    return True
            case AutoReplyMatchType.starts_with.value:
                if text.startswith(kw):
                    return True
            case AutoReplyMatchType.ends_with.value:
                if text.endswith(kw):
                    return True
            case AutoReplyMatchType.regex.value:
                try:
                    if re.search(keyword, text):
                        return True
                except re.error:
                    pass

    return False


async def get_match_count(
    session: AsyncSession,
    chat_id: int,
) -> int:
    """
    获取群组自动回复总匹配次数

    Args:
        session: 数据库会话
        chat_id: 群组 ID

    Returns:
        总匹配次数
    """
    rules = await ServiceBase._get_list(
        session,
        AutoReplyRule,
        filters={"chat_id": chat_id},
    )
    return sum(rule.match_count for rule in rules)
