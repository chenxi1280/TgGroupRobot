from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import AutoReplyRule
from bot.models.enums import AutoReplyMatchType


@dataclass
class CreateResult:
    """创建自动回复规则结果"""
    success: bool
    reason: Literal[
        "ok",
        "invalid_keywords",
        "invalid_reply",
        "invalid_match_type",
    ]
    rule: AutoReplyRule | None = None


@dataclass
class MatchResult:
    """匹配结果"""
    matched: bool
    rule: AutoReplyRule | None = None
    reply_content: str | None = None


async def create_auto_reply_rule(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    keywords: list[str],
    reply_content: str,
    match_type: str = AutoReplyMatchType.contains.value,
    case_sensitive: bool = False,
) -> CreateResult:
    """创建自动回复规则"""
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
    return CreateResult(success=True, reason="ok", rule=rule)


async def get_auto_reply_rule(session: AsyncSession, rule_id: int) -> AutoReplyRule | None:
    """获取自动回复规则"""
    stmt = select(AutoReplyRule).where(AutoReplyRule.id == rule_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_chat_auto_reply_rules(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[AutoReplyRule]:
    """获取群组的自动回复规则列表"""
    stmt = select(AutoReplyRule).where(AutoReplyRule.chat_id == chat_id)
    if active_only:
        stmt = stmt.where(AutoReplyRule.is_active == True)
    stmt = stmt.order_by(AutoReplyRule.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def toggle_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
) -> bool:
    """切换自动回复规则激活状态"""
    rule = await get_auto_reply_rule(session, rule_id)
    if not rule:
        return False
    rule.is_active = not rule.is_active
    return True


async def delete_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
) -> bool:
    """删除自动回复规则"""
    rule = await get_auto_reply_rule(session, rule_id)
    if not rule:
        return False
    await session.delete(rule)
    return True


async def match_auto_reply(
    session: AsyncSession,
    chat_id: int,
    message_text: str,
) -> MatchResult:
    """匹配自动回复规则"""
    rules = await get_chat_auto_reply_rules(session, chat_id, active_only=True)

    for rule in rules:
        if _match_rule(rule, message_text):
            # 增加匹配计数
            rule.match_count += 1
            return MatchResult(
                matched=True,
                rule=rule,
                reply_content=rule.reply_content,
            )

    return MatchResult(matched=False, rule=None, reply_content=None)


def _match_rule(rule: AutoReplyRule, text: str) -> bool:
    """检查消息是否匹配规则"""
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
    """获取群组自动回复总匹配次数"""
    stmt = select(AutoReplyRule).where(AutoReplyRule.chat_id == chat_id)
    result = await session.execute(stmt)
    rules = result.scalars().all()
    return sum(rule.match_count for rule in rules)
