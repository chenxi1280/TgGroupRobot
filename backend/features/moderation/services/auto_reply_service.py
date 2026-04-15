from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.moderation.services.auto_reply_matching import match_auto_reply_impl, match_rule
from backend.features.moderation.services.auto_reply_mutations import (
    create_auto_reply_rule_impl,
    delete_auto_reply_rule_impl,
    move_auto_reply_rule_impl,
    toggle_auto_reply_rule_impl,
    update_auto_reply_rule_impl,
)
from backend.features.moderation.services.auto_reply_queries import (
    get_auto_reply_rule as _get_auto_reply_rule,
)
from backend.features.moderation.services.auto_reply_queries import (
    get_auto_reply_rule_in_chat as _get_auto_reply_rule_in_chat,
)
from backend.features.moderation.services.auto_reply_queries import (
    get_chat_auto_reply_rules as _get_chat_auto_reply_rules,
)
from backend.features.moderation.services.auto_reply_queries import (
    get_match_count as _get_match_count,
)
from backend.features.moderation.services.auto_reply_queries import (
    get_next_sort_order as _get_next_sort_order,
)
from backend.platform.db.schema.models.core import AutoReplyRule
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult, MatchResult


def get_auto_reply_enable_error(rule: AutoReplyRule) -> str | None:
    keywords = [str(item).strip() for item in (getattr(rule, "keywords", None) or [])]
    if not any(keywords):
        return "请先配置关键词"
    if not str(getattr(rule, "reply_content", "") or "").strip():
        return "请先配置文本内容"
    return None


async def create_auto_reply_draft(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
) -> AutoReplyRule:
    rule = AutoReplyRule(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        keywords=[],
        reply_content="",
        cover_media_type=None,
        cover_media_file_id=None,
        buttons=[],
        match_type=AutoReplyMatchType.exact.value,
        case_sensitive=False,
        sort_order=await get_next_sort_order(session, chat_id),
        delete_source=False,
        delete_reply_delay_seconds=0,
        is_active=False,
        stop_after_match=True,
    )
    session.add(rule)
    await session.flush()
    return rule


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
    return await create_auto_reply_rule_impl(
        session,
        chat_id,
        created_by_user_id,
        keywords,
        reply_content,
        match_type=match_type,
        case_sensitive=case_sensitive,
        delete_source=delete_source,
        delete_reply_delay_seconds=delete_reply_delay_seconds,
        cover_media_type=cover_media_type,
        cover_media_file_id=cover_media_file_id,
        buttons=buttons,
        stop_after_match=stop_after_match,
        get_next_sort_order_func=get_next_sort_order,
    )


async def update_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None = None,
    **updates,
) -> AutoReplyRule | None:
    return await update_auto_reply_rule_impl(
        session,
        rule_id,
        chat_id=chat_id,
        get_auto_reply_rule_func=get_auto_reply_rule,
        get_auto_reply_rule_in_chat_func=get_auto_reply_rule_in_chat,
        **updates,
    )


async def get_auto_reply_rule(session: AsyncSession, rule_id: int) -> AutoReplyRule | None:
    return await _get_auto_reply_rule(session, rule_id)


async def get_auto_reply_rule_in_chat(
    session: AsyncSession,
    chat_id: int,
    rule_id: int,
) -> AutoReplyRule | None:
    return await _get_auto_reply_rule_in_chat(session, chat_id, rule_id)


async def get_chat_auto_reply_rules(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[AutoReplyRule]:
    return await _get_chat_auto_reply_rules(session, chat_id, active_only=active_only)


async def get_next_sort_order(session: AsyncSession, chat_id: int) -> int:
    return await _get_next_sort_order(session, chat_id)


async def toggle_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await toggle_auto_reply_rule_impl(
        session,
        rule_id,
        chat_id=chat_id,
        get_auto_reply_rule_func=get_auto_reply_rule,
        get_auto_reply_rule_in_chat_func=get_auto_reply_rule_in_chat,
    )


async def delete_auto_reply_rule(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await delete_auto_reply_rule_impl(
        session,
        rule_id,
        chat_id=chat_id,
        get_auto_reply_rule_func=get_auto_reply_rule,
        get_auto_reply_rule_in_chat_func=get_auto_reply_rule_in_chat,
    )


async def move_auto_reply_rule(
    session: AsyncSession,
    *,
    chat_id: int,
    rule_id: int,
    direction: str,
) -> bool:
    return await move_auto_reply_rule_impl(
        session,
        chat_id=chat_id,
        rule_id=rule_id,
        direction=direction,
        get_chat_auto_reply_rules_func=get_chat_auto_reply_rules,
    )


async def match_auto_reply(
    session: AsyncSession,
    chat_id: int,
    message_text: str,
) -> MatchResult:
    return await match_auto_reply_impl(
        session,
        chat_id,
        message_text,
        get_chat_auto_reply_rules_func=get_chat_auto_reply_rules,
    )


def _match_rule(rule: AutoReplyRule, text: str) -> bool:
    return match_rule(rule, text)


async def get_match_count(
    session: AsyncSession,
    chat_id: int,
) -> int:
    return await _get_match_count(session, chat_id)
