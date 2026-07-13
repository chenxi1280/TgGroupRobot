from __future__ import annotations

import re

from telegram import Message

from backend.features.moderation.services.anti_spam_detection import _forward_source_ids
from backend.features.moderation.services.anti_spam_rules import URL_RE
from backend.features.moderation.services.garbage_guard_rules import get_rule_config
from backend.platform.db.schema.models.core import ChatSettings
from backend.features.moderation.services.garbage_guard_types import GarbageViolation

CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
LETTER_RE = re.compile(r"[A-Za-z]")


def _message_text(message: Message) -> str:
    return getattr(message, "text", None) or getattr(message, "caption", None) or ""


def _full_name(message: Message) -> str:
    user = getattr(message, "from_user", None)
    if user is None:
        return ""
    return " ".join(part for part in [user.first_name, user.last_name] if part)


def _has_external_forward(message: Message) -> bool:
    direct_fields = ("forward_origin", "forward_from_chat", "forward_from", "forward_date")
    if any(getattr(message, field, None) is not None for field in direct_fields):
        return True
    chat_id, user_id = _forward_source_ids(message)
    return chat_id is not None or user_id is not None


def _has_inline_buttons(message: Message) -> bool:
    markup = getattr(message, "reply_markup", None)
    return bool(getattr(markup, "inline_keyboard", None))


def _has_foreign_name(message: Message) -> bool:
    full_name = _full_name(message).strip()
    if not full_name:
        return False
    return not CHINESE_RE.search(full_name) and bool(LETTER_RE.search(full_name))


def _violation(message: Message, rule_id: str, *, rule: str, detail: str) -> GarbageViolation:
    return GarbageViolation(
        rule_id=rule_id,
        rule=rule,
        detail=detail,
        message_ids_to_delete=[message.message_id],
    )


def _detect_long_message(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    text = _message_text(message)
    config = get_rule_config(settings, "long_message")
    max_length = int(config["message_max_length"])
    if config["enabled"] and len(text) >= max_length:
        return _violation(message, "long_message", rule="long_message", detail=f"消息长度 {len(text)} 字，达到/超过 {max_length} 字限制")
    return None


def _detect_long_name(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    config = get_rule_config(settings, "long_name")
    name_length = len(_full_name(message))
    max_length = int(config["name_max_length"])
    if config["enabled"] and name_length > max_length:
        return _violation(message, "long_name", rule="long_name", detail=f"昵称长度 {name_length} 字，超过 {max_length} 字限制")
    return None


def _detect_link(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    text = _message_text(message)
    config = get_rule_config(settings, "block_links")
    if config["enabled"] and text and URL_RE.search(text.lower()):
        return _violation(message, "block_links", rule="link", detail="消息包含链接")
    return None


def _detect_buttons(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    config = get_rule_config(settings, "block_buttons")
    if config["enabled"] and _has_inline_buttons(message):
        return _violation(message, "block_buttons", rule="button", detail="消息包含按钮")
    return None


def _detect_spam_user(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    config = get_rule_config(settings, "spam_user")
    user = getattr(message, "from_user", None)
    if not config["enabled"] or user is None:
        return None
    if config["check_no_username"] and not (user.username or "").strip():
        return _violation(message, "spam_user", rule="no_username", detail="用户没有用户名")
    if config["check_foreign_name"] and _has_foreign_name(message):
        return _violation(message, "spam_user", rule="foreign_name", detail=f"昵称疑似外文: {_full_name(message)}")
    return None


def _detect_forward(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    config = get_rule_config(settings, "block_forwards")
    if config["enabled"] and _has_external_forward(message):
        return _violation(message, "block_forwards", rule="external_forward", detail="转发或引用外部消息")
    return None


_GARBAGE_DETECTORS = (
    _detect_long_message,
    _detect_long_name,
    _detect_link,
    _detect_buttons,
    _detect_spam_user,
    _detect_forward,
)


def detect_garbage_violation(settings: ChatSettings, message: Message) -> GarbageViolation | None:
    for detector in _GARBAGE_DETECTORS:
        violation = detector(settings, message)
        if violation is not None:
            return violation
    return None
