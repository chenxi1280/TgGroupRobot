from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AutoReplyRule
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import MatchResult

RuleListLoader = Callable[[AsyncSession, int, bool], Awaitable[list[AutoReplyRule]]]


def _keyword_matches(
    match_type: str,
    text: str,
    keyword: str,
    *,
    case_sensitive: bool,
) -> bool:
    if match_type == AutoReplyMatchType.regex.value:
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(keyword, text, flags=flags) is not None
    normalized_text = text if case_sensitive else text.casefold()
    normalized_keyword = keyword if case_sensitive else keyword.casefold()
    if match_type == AutoReplyMatchType.exact.value:
        return normalized_text == normalized_keyword
    if match_type == AutoReplyMatchType.contains.value:
        return normalized_keyword in normalized_text
    if match_type == AutoReplyMatchType.starts_with.value:
        return normalized_text.startswith(normalized_keyword)
    if match_type == AutoReplyMatchType.ends_with.value:
        return normalized_text.endswith(normalized_keyword)
    raise ValueError(f"unsupported auto reply match type: {match_type}")


def match_rule(rule: AutoReplyRule, text: str) -> bool:
    return any(
        _keyword_matches(
            rule.match_type,
            text,
            keyword,
            case_sensitive=rule.case_sensitive,
        )
        for keyword in rule.keywords
    )


async def match_auto_reply_impl(
    session: AsyncSession,
    chat_id: int,
    message_text: str,
    *,
    get_chat_auto_reply_rules_func: RuleListLoader,
) -> MatchResult:
    rules = await get_chat_auto_reply_rules_func(session, chat_id, active_only=True)

    matched_rules: list[AutoReplyRule] = []
    for rule in rules:
        if match_rule(rule, message_text):
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
