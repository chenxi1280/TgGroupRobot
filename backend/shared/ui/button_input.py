from __future__ import annotations

import json
import re
from typing import Any

from backend.features.automation.services.scheduled_message_service_validation import (
    ScheduledMessageValidationMixin,
)
from backend.shared.services.base import ValidationError

DEFAULT_MAX_BUTTON_COLS = 4
_ROW_ITEM_SPLIT_RE = re.compile(r"\s*[;；]\s*")


def is_clear_button_input(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    if text == "清空":
        return True
    command = text.split(maxsplit=1)[0].lower() if text else ""
    return command == "/clear" or command.startswith("/clear@")


def split_button_rows(
    rows: list[list[dict[str, str]]],
    *,
    max_cols: int = DEFAULT_MAX_BUTTON_COLS,
) -> list[list[dict[str, str]]]:
    if max_cols <= 0:
        raise ValidationError("每行按钮数量必须大于 0")

    split_rows: list[list[dict[str, str]]] = []
    for row in rows:
        for index in range(0, len(row), max_cols):
            chunk = row[index:index + max_cols]
            if chunk:
                split_rows.append(chunk)
    return split_rows


def normalize_button_rows(
    buttons: list[Any],
    *,
    max_cols: int = DEFAULT_MAX_BUTTON_COLS,
) -> list[list[dict[str, str]]]:
    normalized = ScheduledMessageValidationMixin.normalize_buttons_config(buttons)
    return split_button_rows(normalized, max_cols=max_cols)


def parse_button_rows(
    raw_text: str,
    *,
    allow_empty: bool = False,
    allow_clear: bool = True,
    max_cols: int = DEFAULT_MAX_BUTTON_COLS,
) -> list[list[dict[str, str]]]:
    raw = (raw_text or "").strip()
    if allow_clear and is_clear_button_input(raw):
        return []
    if not raw:
        if allow_empty:
            return []
        raise ValidationError("按钮配置不能为空。")

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"按钮 JSON 格式错误：{exc.msg}") from exc
        return normalize_button_rows(parsed, max_cols=max_cols)

    rows: list[list[dict[str, str]]] = []
    for row_index, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        row: list[dict[str, str]] = []
        items = [item.strip() for item in _ROW_ITEM_SPLIT_RE.split(line) if item.strip()]
        for col_index, item in enumerate(items, start=1):
            if "|" not in item:
                raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮格式错误，请使用 文本|链接")
            button_text, button_url = [part.strip() for part in item.split("|", 1)]
            if not button_text or not button_url:
                raise ValidationError("按钮文案和 URL 不能为空。")
            row.append({"text": button_text, "url": button_url})

        if row:
            rows.append(row)

    if not rows:
        if allow_empty:
            return []
        raise ValidationError("未解析到有效按钮。")
    return normalize_button_rows(rows, max_cols=max_cols)
