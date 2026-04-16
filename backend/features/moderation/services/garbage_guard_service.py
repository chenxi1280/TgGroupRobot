from __future__ import annotations

import re
from dataclasses import dataclass, field

from telegram import Message
from telegram.ext import ContextTypes

from backend.features.moderation.services.anti_spam_detection import _forward_source_ids
from backend.features.moderation.services.anti_spam_rules import URL_RE
from backend.features.moderation.services.garbage_guard_rules import (
    RULE_DEFINITIONS,
    get_rule_config,
)
from backend.features.moderation.services.moderation_service import (
    build_moderation_notice,
    record_violation,
    resolve_effective_action,
    send_temporary_notice,
)
from backend.features.moderation.services.moderation_warning_service import WarningResult, add_warning
from backend.platform.db.schema.models.core import ChatSettings
from backend.shared.services.action_executor import ActionExecutor


CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
LETTER_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class GarbageViolation:
    rule_id: str
    rule: str
    detail: str
    message_ids_to_delete: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class GarbagePunishmentResult:
    applied: bool
    action_label: str
    warning: WarningResult | None = None
    threshold_reached: bool = False


def _message_text(message: Message) -> str:
    return getattr(message, "text", None) or getattr(message, "caption", None) or ""


def _full_name(message: Message) -> str:
    user = getattr(message, "from_user", None)
    if user is None:
        return ""
    return " ".join(part for part in [user.first_name, user.last_name] if part)


def _display_name_len(message: Message) -> int:
    return len(_full_name(message))


def _has_external_forward(message: Message) -> bool:
    if getattr(message, "forward_origin", None) is not None:
        return True
    if getattr(message, "forward_from_chat", None) is not None:
        return True
    if getattr(message, "forward_from", None) is not None:
        return True
    if getattr(message, "forward_date", None) is not None:
        return True
    chat_id, user_id = _forward_source_ids(message)
    return chat_id is not None or user_id is not None


def _has_inline_buttons(message: Message) -> bool:
    markup = getattr(message, "reply_markup", None)
    inline_keyboard = getattr(markup, "inline_keyboard", None)
    return bool(inline_keyboard)


def _has_foreign_name(message: Message) -> bool:
    full_name = _full_name(message).strip()
    if not full_name:
        return False
    return not CHINESE_RE.search(full_name) and bool(LETTER_RE.search(full_name))


def detect_garbage_violation(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    text = _message_text(message)

    long_message = get_rule_config(settings, "long_message")
    if long_message["enabled"] and len(text) > int(long_message["message_max_length"]):
        return GarbageViolation(
            rule_id="long_message",
            rule="long_message",
            detail=f"len={len(text)},max={long_message['message_max_length']}",
            message_ids_to_delete=[message.message_id],
        )

    long_name = get_rule_config(settings, "long_name")
    if long_name["enabled"] and _display_name_len(message) > int(long_name["name_max_length"]):
        return GarbageViolation(
            rule_id="long_name",
            rule="long_name",
            detail=f"name_len={_display_name_len(message)},max={long_name['name_max_length']}",
            message_ids_to_delete=[message.message_id],
        )

    block_links = get_rule_config(settings, "block_links")
    if block_links["enabled"] and text and URL_RE.search(text.lower()):
        return GarbageViolation(
            rule_id="block_links",
            rule="link",
            detail="url detected",
            message_ids_to_delete=[message.message_id],
        )

    block_buttons = get_rule_config(settings, "block_buttons")
    if block_buttons["enabled"] and _has_inline_buttons(message):
        return GarbageViolation(
            rule_id="block_buttons",
            rule="button",
            detail="inline keyboard detected",
            message_ids_to_delete=[message.message_id],
        )

    spam_user = get_rule_config(settings, "spam_user")
    user = getattr(message, "from_user", None)
    if spam_user["enabled"] and user is not None:
        if spam_user["check_no_username"] and not (user.username or "").strip():
            return GarbageViolation(
                rule_id="spam_user",
                rule="no_username",
                detail="username missing",
                message_ids_to_delete=[message.message_id],
            )
        if spam_user["check_foreign_name"] and _has_foreign_name(message):
            return GarbageViolation(
                rule_id="spam_user",
                rule="foreign_name",
                detail=f"name={_full_name(message)}",
                message_ids_to_delete=[message.message_id],
            )

    block_forwards = get_rule_config(settings, "block_forwards")
    if block_forwards["enabled"] and _has_external_forward(message):
        return GarbageViolation(
            rule_id="block_forwards",
            rule="external_forward",
            detail="external forward detected",
            message_ids_to_delete=[message.message_id],
        )

    return None


async def apply_garbage_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    settings: ChatSettings,
    chat_id: int,
    target_user_id: int,
    target_label: str,
    rule_id: str,
    detail: str,
    message_ids: list[int] | None = None,
    sender_chat_id: int | None = None,
    actor_user_id: int | None = None,
    record_message_id: int | None = None,
) -> GarbagePunishmentResult:
    config = get_rule_config(settings, rule_id)
    message_ids = sorted(set(message_ids or []))
    action_parts: list[str] = []
    applied = False

    if bool(config.get("delete_message")) and message_ids:
        result = await ActionExecutor.delete_many(context, chat_id=chat_id, message_ids=message_ids)
        applied = result.applied or applied
        action_parts.append("delete")

    warning_result: WarningResult | None = None
    threshold_reached = True
    if bool(config.get("warn_enabled")) and target_user_id > 0:
        warning_result = await add_warning(
            session,
            chat_id=chat_id,
            user_id=target_user_id,
            rule=rule_id,
            threshold=int(config.get("warn_threshold", 3) or 3),
        )
        threshold_reached = warning_result.threshold_reached
        applied = True
        action_parts.append("warn")

    should_escalate = threshold_reached or not bool(config.get("warn_enabled"))
    if should_escalate:
        if bool(config.get("kick_enabled")):
            resolution = await resolve_effective_action(
                context,
                chat_id,
                target_user_id,
                "kick",
                sender_chat_id=sender_chat_id,
            )
            result = await ActionExecutor.execute(
                context,
                action=resolution.action,
                chat_id=chat_id,
                user_id=target_user_id,
                actor_user_id=actor_user_id,
                message_id=message_ids[0] if message_ids else record_message_id,
                sender_chat_id=sender_chat_id,
                reason=detail or rule_id,
            )
            applied = result.applied or applied
            action_parts.append(resolution.action)
        elif bool(config.get("mute_enabled")):
            resolution = await resolve_effective_action(
                context,
                chat_id,
                target_user_id,
                "mute",
                sender_chat_id=sender_chat_id,
            )
            result = await ActionExecutor.execute(
                context,
                action=resolution.action,
                chat_id=chat_id,
                user_id=target_user_id,
                actor_user_id=actor_user_id,
                message_id=message_ids[0] if message_ids else record_message_id,
                mute_seconds=int(config.get("mute_seconds", 3600) or 3600),
                sender_chat_id=sender_chat_id,
                reason=detail or rule_id,
            )
            applied = result.applied or applied
            action_parts.append(resolution.action)

    action_label = "+".join(action_parts) if action_parts else "none"
    if target_user_id > 0:
        await record_violation(
            session,
            chat_id=chat_id,
            user_id=target_user_id,
            message_id=record_message_id,
            rule=rule_id,
            detail=detail,
            action=action_label[:32],
        )

    if bool(config.get("notice_enabled")):
        warning_text = ""
        if warning_result is not None:
            warning_text = f"警告次数: {warning_result.count}/{warning_result.threshold}"
        text = str(config.get("notice_text") or "").strip()
        if not text:
            title = f"🚫 {RULE_DEFINITIONS.get(rule_id).label if rule_id in RULE_DEFINITIONS else '垃圾防护'}已处理"
            text = build_moderation_notice(
                title,
                target_label,
                detail,
                action_label,
                extra_lines=[warning_text] if warning_text else None,
            )
        await send_temporary_notice(
            context.bot,
            chat_id=chat_id,
            text=text,
            delete_after_seconds=int(config.get("notice_delete_seconds", 10) or 10),
        )

    return GarbagePunishmentResult(
        applied=applied,
        action_label=action_label,
        warning=warning_result,
        threshold_reached=threshold_reached,
    )
