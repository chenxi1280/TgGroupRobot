from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.moderation.services.auto_reply_validation import normalize_update_payload, validate_create_inputs
from backend.platform.db.schema.models.core import AutoReplyRule
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import CreateResult

SortOrderLoader = Callable[[AsyncSession, int], Awaitable[int]]
RuleLoader = Callable[[AsyncSession, int], Awaitable[AutoReplyRule | None]]
ScopedRuleLoader = Callable[[AsyncSession, int, int], Awaitable[AutoReplyRule | None]]
RuleListLoader = Callable[[AsyncSession, int, bool], Awaitable[list[AutoReplyRule]]]


async def create_auto_reply_rule_impl(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    keywords: list[str],
    reply_content: str,
    *,
    match_type: str = AutoReplyMatchType.contains.value,
    case_sensitive: bool = False,
    delete_source: bool = False,
    delete_reply_delay_seconds: int = 0,
    cover_media_type: str | None = None,
    cover_media_file_id: str | None = None,
    buttons: list | None = None,
    stop_after_match: bool = True,
    get_next_sort_order_func: SortOrderLoader,
) -> CreateResult:
    invalid_result, normalized_keywords, normalized_buttons = validate_create_inputs(
        keywords=keywords,
        reply_content=reply_content,
        match_type=match_type,
        delete_reply_delay_seconds=delete_reply_delay_seconds,
        buttons=buttons,
    )
    if invalid_result is not None:
        return invalid_result

    sort_order = await get_next_sort_order_func(session, chat_id)
    rule = AutoReplyRule(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        keywords=normalized_keywords,
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


async def update_auto_reply_rule_impl(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None,
    get_auto_reply_rule_func: RuleLoader,
    get_auto_reply_rule_in_chat_func: ScopedRuleLoader,
    **updates,
) -> AutoReplyRule | None:
    rule = await (
        get_auto_reply_rule_in_chat_func(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule_func(session, rule_id)
    )
    if rule is None:
        return None

    normalized_updates = normalize_update_payload(updates)
    await ServiceBase._update_entity(session, rule, normalized_updates)
    return rule


async def toggle_auto_reply_rule_impl(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None,
    get_auto_reply_rule_func: RuleLoader,
    get_auto_reply_rule_in_chat_func: ScopedRuleLoader,
) -> bool:
    rule = await (
        get_auto_reply_rule_in_chat_func(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule_func(session, rule_id)
    )
    if not rule:
        return False

    await ServiceBase._update_entity(session, rule, {"is_active": not rule.is_active})
    return True


async def delete_auto_reply_rule_impl(
    session: AsyncSession,
    rule_id: int,
    *,
    chat_id: int | None,
    get_auto_reply_rule_func: RuleLoader,
    get_auto_reply_rule_in_chat_func: ScopedRuleLoader,
) -> bool:
    rule = await (
        get_auto_reply_rule_in_chat_func(session, chat_id, rule_id)
        if chat_id is not None
        else get_auto_reply_rule_func(session, rule_id)
    )
    if not rule:
        return False

    await ServiceBase._delete_entity(session, rule)
    return True


async def move_auto_reply_rule_impl(
    session: AsyncSession,
    *,
    chat_id: int,
    rule_id: int,
    direction: str,
    get_chat_auto_reply_rules_func: RuleListLoader,
) -> bool:
    rules = await get_chat_auto_reply_rules_func(session, chat_id)
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
    current_rule.sort_order, swap_rule.sort_order = swap_rule.sort_order, current_rule.sort_order
    await session.flush()
    return True
