from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AutoReplyRule
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.base import ServiceBase
from backend.shared.services.result import MatchResult

RuleListLoader = Callable[[AsyncSession, int, bool], Awaitable[list[AutoReplyRule]]]


def match_rule(rule: AutoReplyRule, text: str) -> bool:
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
