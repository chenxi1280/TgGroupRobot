from __future__ import annotations

import re

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.schema.models.enums import AutoReplyMatchType
from backend.shared.services.result import CreateResult


def validate_create_inputs(
    *,
    keywords: list[str],
    reply_content: str,
    match_type: str,
    delete_reply_delay_seconds: int,
    buttons: list | None,
) -> tuple[CreateResult | None, list[str], list[list[dict[str, str]]]]:
    if not keywords or not all(k.strip() for k in keywords):
        return CreateResult(success=False, reason="invalid_keywords"), [], []

    if not reply_content or not reply_content.strip():
        return CreateResult(success=False, reason="invalid_reply"), [], []

    if delete_reply_delay_seconds < 0:
        return CreateResult(success=False, reason="invalid_delete_delay"), [], []

    normalized_buttons: list[list[dict[str, str]]] = []
    if buttons:
        try:
            normalized_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
        except Exception:
            return CreateResult(success=False, reason="invalid_buttons"), [], []

    valid_types = [e.value for e in AutoReplyMatchType]
    if match_type not in valid_types:
        return CreateResult(success=False, reason="invalid_match_type"), [], []

    normalized_keywords = [k.strip() for k in keywords]
    if match_type == AutoReplyMatchType.regex.value:
        for keyword in normalized_keywords:
            try:
                re.compile(keyword)
            except re.error:
                return CreateResult(success=False, reason="invalid_keywords"), [], []

    return None, normalized_keywords, normalized_buttons


def normalize_update_payload(updates: dict) -> dict:
    normalized = dict(updates)

    if "keywords" in normalized and normalized["keywords"] is not None:
        keywords = [item.strip() for item in normalized["keywords"] if str(item).strip()]
        if not keywords:
            raise ValueError("关键词不能为空")
        normalized["keywords"] = keywords

    if "reply_content" in normalized and normalized["reply_content"] is not None:
        if not str(normalized["reply_content"]).strip():
            raise ValueError("回复内容不能为空")

    if "delete_reply_delay_seconds" in normalized and normalized["delete_reply_delay_seconds"] is not None:
        if int(normalized["delete_reply_delay_seconds"]) < 0:
            raise ValueError("延迟删除必须大于等于 0")

    if "buttons" in normalized and normalized["buttons"] is not None:
        normalized["buttons"] = ScheduledMessageService.normalize_buttons_config(normalized["buttons"])

    return normalized
