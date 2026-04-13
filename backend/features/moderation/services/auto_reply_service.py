from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AutoReplyRule
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.base import ServiceBase
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.shared.services.result import CreateResult, MatchResult


async def create_auto_reply_rule(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    keywords: list[str],
    reply_content: str,
    match_type: str = AutoReplyMatchType.contains.value,
    case_sensitive: bool = False,
    delete_source: bool = False,
    delete_reply_delay_seconds: int = 0,
    cover_media_type: str | None = None,
    cover_media_file_id: str | None = None,
    buttons: list | None = None,
    stop_after_match: bool = True,
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

    if delete_reply_delay_seconds < 0:
        return CreateResult(success=False, reason="invalid_delete_delay")

    normalized_buttons: list[list[dict[str, str]]] = []
    if buttons:
        try:
            normalized_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
        except Exception:
            return CreateResult(success=False, reason="invalid_buttons")

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

    sort_order = await get_next_sort_order(session, chat_id)
    rule = AutoReplyRule(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        keywords=[k.strip() for k in keywords],
        reply_content=reply_content,
        cover_media_type=cover_media_type,
        cover_media_file_id=cover_media_file_id,
        buttons=normalized_buttons,
        match_type=match_type,
        case_sensitive=case_sensitive,
        sort_order=sort_order,
        delete_source=delete_source,
        delete_reply_delay_seconds=delete_reply_delay_seconds,
        stop_after_match=stop_after_match,
    )
    session.add(rule)
    await session.flush()
    return CreateResult(success=True, reason="ok", entity=rule, entity_id=rule.id)


async def update_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None = None,
    **updates,
) -> AutoReplyRule | None:
    rule = await (
        get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule(session, rule_id)
    )
    if rule is None:
        return None

    if "keywords" in updates and updates["keywords"] is not None:
        keywords = [item.strip() for item in updates["keywords"] if str(item).strip()]
        if not keywords:
            raise ValueError("关键词不能为空")
        updates["keywords"] = keywords

    if "reply_content" in updates and updates["reply_content"] is not None:
        if not str(updates["reply_content"]).strip():
            raise ValueError("回复内容不能为空")

    if "delete_reply_delay_seconds" in updates and updates["delete_reply_delay_seconds"] is not None:
        if int(updates["delete_reply_delay_seconds"]) < 0:
            raise ValueError("延迟删除必须大于等于 0")

    if "buttons" in updates and updates["buttons"] is not None:
        updates["buttons"] = ScheduledMessageService.normalize_buttons_config(updates["buttons"])

    await ServiceBase._update_entity(session, rule, updates)
    return rule


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


async def get_auto_reply_rule_in_chat(
    session: AsyncSession,
    chat_id: int,
    rule_id: int,
) -> AutoReplyRule | None:
    """按群组作用域获取自动回复规则，避免跨群访问。"""
    stmt = select(AutoReplyRule).where(
        AutoReplyRule.id == rule_id,
        AutoReplyRule.chat_id == chat_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


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
    stmt = (
        select(AutoReplyRule)
        .where(AutoReplyRule.chat_id == chat_id)
        .order_by(AutoReplyRule.sort_order.asc(), AutoReplyRule.id.asc())
    )
    if active_only:
        stmt = stmt.where(AutoReplyRule.is_active == True)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_next_sort_order(session: AsyncSession, chat_id: int) -> int:
    stmt = select(func.max(AutoReplyRule.sort_order)).where(AutoReplyRule.chat_id == chat_id)
    result = await session.execute(stmt)
    max_sort = result.scalar_one_or_none()
    return int(max_sort or 0) + 1


async def toggle_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    """
    切换自动回复规则激活状态

    Args:
        session: 数据库会话
        rule_id: 规则 ID

    Returns:
        是否切换成功
    """
    rule = await (
        get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule(session, rule_id)
    )
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
    *,
    chat_id: int | None = None,
) -> bool:
    """
    删除自动回复规则

    Args:
        session: 数据库会话
        rule_id: 规则 ID

    Returns:
        是否删除成功
    """
    rule = await (
        get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule(session, rule_id)
    )
    if not rule:
        return False
    await ServiceBase._delete_entity(session, rule)
    return True


async def move_auto_reply_rule(
    session: AsyncSession,
    *,
    chat_id: int,
    rule_id: int,
    direction: str,
) -> bool:
    rules = await get_chat_auto_reply_rules(session, chat_id)
    current_index = next((idx for idx, rule in enumerate(rules) if rule.id == rule_id), None)
    if current_index is None:
        return False

    if direction == "up":
        swap_index = current_index - 1
    elif direction == "down":
        swap_index = current_index + 1
    else:
        return False

    if swap_index < 0 or swap_index >= len(rules):
        return False

    current_rule = rules[current_index]
    swap_rule = rules[swap_index]
    current_order = current_rule.sort_order
    current_rule.sort_order = swap_rule.sort_order
    swap_rule.sort_order = current_order
    await session.flush()
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

    matched_rules: list[AutoReplyRule] = []

    for rule in rules:
        if _match_rule(rule, message_text):
            # 增加匹配计数
            await ServiceBase._update_entity(
                session,
                rule,
                {"match_count": rule.match_count + 1},
            )
            matched_rules.append(rule)
            if getattr(rule, "stop_after_match", True):
                break

    if matched_rules:
        return MatchResult(
            success=True,
            reason="matched",
            rule=matched_rules[0],
            reply_content=matched_rules[0].reply_content,
            matched_rules=matched_rules,
        )

    return MatchResult(
        success=False,
        reason="no_match",
        rule=None,
        reply_content=None,
        matched_rules=[],
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
