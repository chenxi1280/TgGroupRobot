from __future__ import annotations

from typing import Any

from backend.features.automation.services.scheduled_message_service_validation import (
    ScheduledMessageValidationMixin,
)
from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import DEFAULT_MAX_BUTTON_COLS, split_button_rows
_SANITIZE_TEXT_TRIGGER_PAYLOAD_THRESHOLD_128 = 128


AUTO_REPLY_TEXT_TRIGGER = "text_trigger"


def sanitize_text_trigger_payload(value: str) -> str:
    payload = str(value or "").strip()
    if not payload:
        raise ValidationError("触发文字不能为空。")
    if len(payload) > _SANITIZE_TEXT_TRIGGER_PAYLOAD_THRESHOLD_128:
        raise ValidationError("触发文字过长，请控制在 128 个字符以内。")
    return payload


def _normalize_button(item: dict[str, Any], *, row_index: int, col_index: int) -> dict[str, str]:
    text = str(item.get("text") or "").strip()
    if not text:
        raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮 text 不能为空")

    action_type = str(item.get("action_type") or "").strip()
    payload = str(item.get("payload") or "").strip()
    if action_type == AUTO_REPLY_TEXT_TRIGGER:
        return {
            "text": text,
            "action_type": AUTO_REPLY_TEXT_TRIGGER,
            "payload": sanitize_text_trigger_payload(payload),
        }

    raw_url = item.get("url", item.get("link", ""))
    url = str(raw_url or "").strip()
    if url:
        return {
            "text": text,
            "url": ScheduledMessageValidationMixin._normalize_button_url(url),
        }

    callback_data = str(item.get("callback_data") or "").strip()
    if callback_data:
        return {"text": text, "callback_data": callback_data}

    raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮缺少链接或触发文字")


def _normalize_row(row: list[Any], *, row_index: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for col_index, item in enumerate(row, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮必须是对象")
        normalized.append(_normalize_button(item, row_index=row_index, col_index=col_index))
    return normalized


def normalize_auto_reply_button_rows(
    buttons: list[Any],
    *,
    max_cols: int = DEFAULT_MAX_BUTTON_COLS,
) -> list[list[dict[str, str]]]:
    if not isinstance(buttons, list):
        raise ValidationError("按钮配置必须是 JSON 数组")
    if not buttons:
        return []

    if all(isinstance(item, dict) for item in buttons):
        rows = [buttons]
    elif all(isinstance(item, list) for item in buttons):
        rows = buttons
    else:
        raise ValidationError("按钮格式必须是 [{text,url}] 或 [[{text,url}]]")

    normalized_rows: list[list[dict[str, str]]] = []
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, list):
            raise ValidationError(f"第 {row_index} 行按钮格式错误")
        normalized_row = _normalize_row(row, row_index=row_index)
        if normalized_row:
            normalized_rows.extend(split_button_rows([normalized_row], max_cols=max_cols))
    return normalized_rows


def find_auto_reply_button(rule, row_index: int, col_index: int) -> dict[str, str] | None:
    try:
        rows = normalize_auto_reply_button_rows(getattr(rule, "buttons", None) or [])
    except ValidationError:
        return None
    if row_index < 0 or col_index < 0 or row_index >= len(rows):
        return None
    row = rows[row_index]
    if col_index >= len(row):
        return None
    return row[col_index]
