from __future__ import annotations

from dataclasses import dataclass

from telegram.ext import ContextTypes

from backend.features.moderation.services.garbage_guard_rules import get_rule_config
from backend.features.moderation.services.moderation_service import (
    build_moderation_action_label,
    build_moderation_notice,
    record_violation,
    resolve_effective_action,
    send_temporary_notice,
)
from backend.features.moderation.services.user_action_runtime import UserActionResult, execute_user_action
from backend.platform.db.schema.models.core import ChatSettings


QUICK_REPLY_RULE_ID = "quick_reply_actions"
QUICK_REPLY_FEATURE = "垃圾防护快捷回复"
MAX_QUICK_REPLY_KEYWORD_LENGTH = 32


@dataclass(frozen=True)
class QuickReplyKeywordInput:
    field: str
    keyword: str


def normalize_quick_reply_keyword(raw_value: str) -> str:
    keyword = raw_value.strip()
    if not keyword:
        raise ValueError("快捷回复词不能为空")
    if len(keyword) > MAX_QUICK_REPLY_KEYWORD_LENGTH:
        raise ValueError(f"快捷回复词不能超过 {MAX_QUICK_REPLY_KEYWORD_LENGTH} 个字符")
    if any(char.isspace() for char in keyword):
        raise ValueError("快捷回复词不能包含空格或换行")
    return keyword


def parse_quick_reply_keyword_input(field: str, raw_value: str) -> QuickReplyKeywordInput:
    if field not in {"mute_keyword", "kick_keyword"}:
        raise ValueError("无效的快捷回复配置项")
    return QuickReplyKeywordInput(field=field, keyword=normalize_quick_reply_keyword(raw_value))


def _same_keyword(text: str, keyword: str) -> bool:
    return text.strip().casefold() == keyword.strip().casefold()


def match_quick_reply_action(settings: ChatSettings, text: str) -> str | None:
    config = get_rule_config(settings, QUICK_REPLY_RULE_ID)
    if not bool(config.get("enabled")):
        return None
    if _same_keyword(text, str(config.get("mute_keyword", "j"))):
        return "mute"
    if _same_keyword(text, str(config.get("kick_keyword", "t"))):
        return "kick"
    return None


async def apply_quick_reply_action(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    settings: ChatSettings,
    chat_id: int,
    target_user_id: int,
    target_label: str,
    action: str,
    actor_user_id: int,
    command_message,
    target_message_id: int | None,
) -> UserActionResult:
    config = get_rule_config(settings, QUICK_REPLY_RULE_ID)
    resolution = await resolve_effective_action(context, chat_id, target_user_id, requested_action=action)
    mute_seconds = int(config.get("mute_seconds", 3600) or 3600)
    detail = "管理员引用回复快捷处置"
    result = await execute_user_action(
        context,
        feature=QUICK_REPLY_FEATURE,
        chat_id=chat_id,
        user_id=target_user_id,
        action=resolution.action,
        detail=detail,
        message=command_message,
        message_id=target_message_id,
        delete_message=bool(config.get("delete_message")),
        mute_seconds=mute_seconds,
        actor_user_id=actor_user_id,
    )
    action_label = build_moderation_action_label(resolution.action, mute_seconds)
    await record_violation(
        session,
        chat_id=chat_id,
        user_id=target_user_id,
        message_id=target_message_id,
        rule=QUICK_REPLY_RULE_ID,
        detail=detail,
        action=action_label[:32],
    )
    await _send_quick_reply_notice(context, chat_id, config, target_label=target_label, detail=detail, action_label=action_label)
    return result


async def _send_quick_reply_notice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    config: dict,
    *, target_label: str,
    detail: str,
    action_label: str,
) -> None:
    if not bool(config.get("notice_enabled")):
        return
    text = str(config.get("notice_text") or "").strip()
    if not text:
        text = build_moderation_notice("🚫 快捷回复已处理", target_label, detail, action_label=action_label)
    await send_temporary_notice(
        context.bot,
        chat_id=chat_id,
        text=text,
        delete_after_seconds=int(config.get("notice_delete_seconds", 10) or 10),
    )
