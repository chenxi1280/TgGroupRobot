from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AutoReplyRule
from backend.shared.services.base import ServiceBase


async def get_auto_reply_rule(session: AsyncSession, rule_id: int) -> AutoReplyRule | None:
    return await ServiceBase._get_by_id(session, AutoReplyRule, rule_id)


async def get_auto_reply_rule_in_chat(
    session: AsyncSession,
    chat_id: int,
    rule_id: int,
) -> AutoReplyRule | None:
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


async def get_match_count(
    session: AsyncSession,
    chat_id: int,
) -> int:
    rules = await ServiceBase._get_list(
        session,
        AutoReplyRule,
        filters={"chat_id": chat_id},
    )
    return sum(rule.match_count for rule in rules)
