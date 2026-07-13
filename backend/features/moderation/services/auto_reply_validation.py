from __future__ import annotations

import re

import structlog
from backend.features.moderation.auto_reply_buttons import normalize_auto_reply_button_rows
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.result import CreateResult

log = structlog.get_logger(__name__)


def _normalize_create_buttons(buttons: list | None) -> list[list[dict[str, str]]] | None:
    if not buttons:
        return []
    try:
        return normalize_auto_reply_button_rows(buttons)
    except Exception as exc:
        log.warning("auto_reply_button_validation_failed", error=str(exc))
        return None


def _valid_regex_keywords(keywords: list[str]) -> bool:
    try:
        for keyword in keywords:
            re.compile(keyword)
    except re.error:
        return False
    return True


def _create_validation_reason(
    keywords: list[str],
    reply_content: str,
    match_type: str,
    *,
    delete_delay: int,
) -> str | None:
    if not keywords or not all(keyword.strip() for keyword in keywords):
        return "invalid_keywords"
    if not reply_content or not reply_content.strip():
        return "invalid_reply"
    if delete_delay < 0:
        return "invalid_delete_delay"
    valid_types = {item.value for item in AutoReplyMatchType}
    return None if match_type in valid_types else "invalid_match_type"


def _normalize_update_keywords(normalized: dict) -> None:
    keywords = normalized.get("keywords")
    if keywords is None:
        return
    cleaned = [item.strip() for item in keywords if str(item).strip()]
    if not cleaned:
        raise ValueError("关键词不能为空")
    normalized["keywords"] = cleaned


def _validate_update_scalars(normalized: dict) -> None:
    reply_content = normalized.get("reply_content")
    if reply_content is not None and not str(reply_content).strip():
        raise ValueError("回复内容不能为空")
    delay = normalized.get("delete_reply_delay_seconds")
    if delay is not None and int(delay) < 0:
        raise ValueError("延迟删除必须大于等于 0")


def validate_create_inputs(
    *,
    keywords: list[str],
    reply_content: str,
    match_type: str,
    delete_reply_delay_seconds: int,
    buttons: list | None,
) -> tuple[CreateResult | None, list[str], list[list[dict[str, str]]]]:
    reason = _create_validation_reason(
        keywords,
        reply_content,
        match_type,
        delete_delay=delete_reply_delay_seconds,
    )
    if reason is not None:
        return CreateResult(success=False, reason=reason), [], []

    normalized_buttons = _normalize_create_buttons(buttons)
    if normalized_buttons is None:
        return CreateResult(success=False, reason="invalid_buttons"), [], []

    normalized_keywords = [k.strip() for k in keywords]
    if match_type == AutoReplyMatchType.regex.value and not _valid_regex_keywords(normalized_keywords):
        return CreateResult(success=False, reason="invalid_keywords"), [], []

    return None, normalized_keywords, normalized_buttons


def normalize_update_payload(updates: dict) -> dict:
    normalized = dict(updates)

    _normalize_update_keywords(normalized)
    _validate_update_scalars(normalized)

    if "buttons" in normalized and normalized["buttons"] is not None:
        normalized["buttons"] = normalize_auto_reply_button_rows(normalized["buttons"])

    return normalized
