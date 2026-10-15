"""Bounded, read-only management searches; never read operational payload bodies."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select

from backend.platform.db.schema.models.automation import AdCampaign
from backend.platform.db.schema.models.moderation import AutoReplyRule
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask

PAGE_SIZE = 8
MAX_QUERY_LENGTH = 100
FILTERS = {"all": "全部", "enabled": "启用", "disabled": "关闭"}


@dataclass(frozen=True)
class ListSpec:
    model: object
    title: str
    key: object
    text: object
    enabled: object
    order: tuple
    detail_prefix: str
    create_prefix: str


SPECS = {
    "autoreply": ListSpec(AutoReplyRule, "💬 自动回复", AutoReplyRule.id,
        cast(AutoReplyRule.keywords, String), AutoReplyRule.is_active,
        (AutoReplyRule.sort_order, AutoReplyRule.id), "auto_reply:detail", "auto_reply:create"),
    "scheduled": ListSpec(ScheduledMessageTask, "⏰ 定时消息", ScheduledMessageTask.short_id,
        ScheduledMessageTask.title, ScheduledMessageTask.enabled,
        (ScheduledMessageTask.created_at.desc(), ScheduledMessageTask.task_id), "sm:open", "sm:add"),
    "ads": ListSpec(AdCampaign, "🎠 轮播广告列表", AdCampaign.id,
        AdCampaign.title, AdCampaign.enabled,
        (AdCampaign.sort_order, AdCampaign.id), "ads:detail", "ads:create"),
}


def normalize_query(value: str) -> str:
    value = value.strip()
    if not value or len(value) > MAX_QUERY_LENGTH:
        raise ValueError(f"请输入 1—{MAX_QUERY_LENGTH} 个字符；查询特殊字符按原文匹配。")
    return value


def search_statement(feature: str, chat_id: int, *, query: str, status: str):
    spec = SPECS[feature]
    stmt = select(spec.model).where(spec.model.chat_id == chat_id)
    if query:
        text_match = func.lower(spec.text).contains(query.lower(), autoescape=True)
        if feature == "autoreply":
            words = func.jsonb_array_elements_text(AutoReplyRule.keywords).table_valued("value")
            text_match = select(1).select_from(words).where(
                func.lower(words.c.value).contains(query.lower(), autoescape=True),
            ).exists()
        stmt = stmt.where(or_(
            text_match,
            cast(spec.key, String) == query.lstrip("#"),
        ))
    if status != "all":
        stmt = stmt.where(spec.enabled == (status == "enabled"))
    return stmt


async def search_page(session, feature: str, *, chat_id: int, query: str, status: str, page: int):
    if status not in FILTERS:
        raise ValueError("无效状态筛选")
    stmt = search_statement(feature, chat_id, query=query, status=status)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    page = min(max(page, 0), max(0, (total - 1) // PAGE_SIZE))
    result = await session.execute(stmt.order_by(*SPECS[feature].order).offset(page * PAGE_SIZE).limit(PAGE_SIZE))
    return list(result.scalars()), total, page
