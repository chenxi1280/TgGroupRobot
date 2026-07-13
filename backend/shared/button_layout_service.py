from __future__ import annotations

from dataclasses import dataclass
from typing import Any


from backend.features.automation.services.scheduled_message_service_validation import ScheduledMessageValidationMixin
from backend.features.moderation.auto_reply_buttons import (
    AUTO_REPLY_TEXT_TRIGGER,
    normalize_auto_reply_button_rows,
    sanitize_text_trigger_payload,
)
from backend.shared.services.base import ValidationError
_SANITIZE_BUTTON_TEXT_THRESHOLD_16 = 16


MAX_BUTTON_COLS = 4
TEXT_INPUT_STATE = "button_editor_text_input"
URL_INPUT_STATE = "button_editor_url_input"
PAYLOAD_INPUT_STATE = "button_editor_payload_input"

ButtonCell = dict[str, str] | None
ButtonGrid = list[list[ButtonCell]]


@dataclass(slots=True)
class ButtonEditorContext:
    module_type: str
    target_chat_id: int
    entity_id: int
    row_index: int | None = None
    col_index: int | None = None


class ButtonLayoutEditorService:
    @staticmethod
    def sanitize_button_text(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValidationError("按钮文字不能为空。")
        if len(text) > _SANITIZE_BUTTON_TEXT_THRESHOLD_16:
            raise ValidationError("按钮文字过长，请控制在 16 个字符以内。")
        return text

    @staticmethod
    def normalize_button_url(value: str) -> str:
        return ScheduledMessageValidationMixin._normalize_button_url(str(value or "").strip())

    @classmethod
    def to_grid(cls, buttons: list | None, *, module_type: str | None = None) -> ButtonGrid:
        normalized = cls._normalize_existing_buttons(buttons or [], module_type=module_type)
        if not normalized:
            return [[]]
        grid: ButtonGrid = []
        for row in normalized:
            grid.append([cls._cell_from_button(item) for item in row])
        return cls._trim_grid(grid)

    @classmethod
    def add_button(
        cls,
        grid: ButtonGrid,
        row_index: int | None = None,
        col_index: int | None = None,
    ) -> tuple[ButtonGrid, int, int]:
        draft = cls._clone_grid(grid)
        if row_index is None or col_index is None:
            row_index, col_index = cls.first_empty_slot(draft)
        elif row_index < 0 or col_index < 0 or col_index >= MAX_BUTTON_COLS:
            raise ValidationError(f"按钮位置无效，每行最多 {MAX_BUTTON_COLS} 个按钮。")
        elif cls.get_cell(draft, row_index, col_index) is not None:
            raise ValidationError("该位置已经有按钮。")
        cls._set_cell(draft, row_index, col_index, value={"text": "", "url": ""})
        return cls._trim_grid(draft), row_index, col_index

    @classmethod
    def clear_buttons(cls) -> ButtonGrid:
        return [[]]

    @classmethod
    def get_cell(cls, grid: ButtonGrid, row_index: int, col_index: int) -> dict[str, str] | None:
        if row_index < 0 or col_index < 0:
            return None
        if row_index >= len(grid):
            return None
        row = grid[row_index]
        if col_index >= len(row):
            return None
        cell = row[col_index]
        if cell is None:
            return None
        return cls._clone_cell(cell)

    @classmethod
    def update_button(
        cls,
        grid: ButtonGrid,
        row_index: int,
        col_index: int,
        *,
        text: str | None = None,
        url: str | None = None,
        action_type: str | None = None,
        payload: str | None = None,
    ) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        cell = cls.get_cell(draft, row_index, col_index)
        if cell is None:
            raise ValidationError("按钮不存在。")
        if text is not None:
            cell["text"] = text
        if url is not None:
            cell["url"] = url
        if action_type is not None:
            cell["action_type"] = action_type
        if payload is not None:
            cell["payload"] = payload
        cls._set_cell(draft, row_index, col_index, value=cell)
        return cls._trim_grid(draft)

    @classmethod
    def delete_button(cls, grid: ButtonGrid, row_index: int, col_index: int) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        if cls.get_cell(draft, row_index, col_index) is None:
            return cls._trim_grid(draft)
        cls._set_cell(draft, row_index, col_index, value=None)
        return cls._trim_grid(draft)

    @classmethod
    def move_button(
        cls,
        grid: ButtonGrid,
        row_index: int,
        col_index: int,
        *, direction: str,
    ) -> tuple[ButtonGrid, int, int, bool]:
        source = cls.get_cell(grid, row_index, col_index)
        if source is None:
            return cls._trim_grid(grid), row_index, col_index, False

        row_delta, col_delta = {
            "up": (-1, 0),
            "down": (1, 0),
            "left": (0, -1),
            "right": (0, 1),
        }.get(direction, (0, 0))
        target_row = row_index + row_delta
        target_col = col_index + col_delta
        if target_row < 0 or target_col < 0 or target_col >= MAX_BUTTON_COLS:
            return cls._trim_grid(grid), row_index, col_index, False

        draft = cls._clone_grid(grid)
        max_target_row = max(target_row, len(draft) - 1)
        while len(draft) <= max_target_row:
            draft.append([])
        target = cls.get_cell(draft, target_row, target_col)
        cls._set_cell(draft, row_index, col_index, value=target)
        cls._set_cell(draft, target_row, target_col, value=source)
        trimmed = cls._trim_grid(draft)
        if cls.get_cell(trimmed, target_row, target_col) == source:
            return trimmed, target_row, target_col, True
        return trimmed, row_index, col_index, False

    @classmethod
    def export_complete_buttons(
        cls,
        grid: ButtonGrid,
        *,
        module_type: str | None = None,
    ) -> list[list[dict[str, str]]]:
        exported: list[list[dict[str, str]]] = []
        for row in grid:
            exported_row = [
                value
                for cell in row
                if cell is not None
                if (value := cls._export_cell(cell, module_type=module_type)) is not None
            ]
            if exported_row:
                exported.extend(cls._chunk_row(exported_row))
        return exported

    @classmethod
    def _export_cell(cls, cell: dict[str, str], *, module_type: str | None) -> dict[str, str] | None:
        text = str(cell.get("text", "")).strip()
        raw_url = str(cell.get("url", "")).strip()
        action_type = str(cell.get("action_type", "")).strip()
        raw_payload = str(cell.get("payload", "")).strip()
        if module_type == "auto_reply" and action_type == AUTO_REPLY_TEXT_TRIGGER:
            if not text or not raw_payload:
                return None
            return {
                "text": cls.sanitize_button_text(text),
                "action_type": AUTO_REPLY_TEXT_TRIGGER,
                "payload": sanitize_text_trigger_payload(raw_payload),
            }
        if not text or not raw_url:
            return None
        return {"text": cls.sanitize_button_text(text), "url": cls.normalize_button_url(raw_url)}

    @staticmethod
    def _chunk_row(row: list[dict[str, str]]) -> list[list[dict[str, str]]]:
        return [row[index:index + MAX_BUTTON_COLS] for index in range(0, len(row), MAX_BUTTON_COLS)]

    @classmethod
    def display_rows(cls, grid: ButtonGrid) -> list[list[dict[str, Any]]]:
        draft = cls._trim_grid(grid)
        add_row, add_col = cls.first_empty_slot(draft)
        rows_to_render = max(len(draft), add_row + 1, 1)
        rows: list[list[dict[str, Any]]] = []
        for row_index in range(rows_to_render):
            row = cls._display_row(draft, row_index)
            if row:
                rows.append(row)
        return rows or [[{"kind": "add", "label": "➕ 按钮", "row": 0, "col": 0}]]

    @classmethod
    def _display_row(cls, grid: ButtonGrid, row_index: int) -> list[dict[str, Any]]:
        row_cells = grid[row_index] if row_index < len(grid) else []
        occupied = [
            col
            for col in range(min(len(row_cells), MAX_BUTTON_COLS))
            if cls.get_cell(grid, row_index, col) is not None
        ]
        show_until = min(max(occupied) + 2, MAX_BUTTON_COLS) if occupied else 1
        return [cls._display_cell(grid, row_index, col) for col in range(show_until)]

    @classmethod
    def _display_cell(cls, grid: ButtonGrid, row_index: int, col_index: int) -> dict[str, Any]:
        cell = cls.get_cell(grid, row_index, col_index)
        if cell is not None:
            return {
                "kind": "cell",
                "label": str(cell.get("text", "")).strip() or "⚠️ 空",
                "row": row_index,
                "col": col_index,
            }
        has_later = any(
            cls.get_cell(grid, row_index, later) is not None
            for later in range(col_index + 1, MAX_BUTTON_COLS)
        )
        return {
            "kind": "empty" if has_later else "add",
            "label": "⚠️ 空" if has_later else "➕ 按钮",
            "row": row_index,
            "col": col_index,
        }

    @classmethod
    def first_empty_slot(cls, grid: ButtonGrid) -> tuple[int, int]:
        draft = cls._trim_grid(grid)
        for row_index in range(max(len(draft), 1)):
            for col_index in range(MAX_BUTTON_COLS):
                if cls.get_cell(draft, row_index, col_index) is None:
                    return row_index, col_index
        return len(draft), 0

    @classmethod
    def _normalize_existing_buttons(
        cls,
        buttons: list,
        *,
        module_type: str | None = None,
    ) -> list[list[dict[str, str]]]:
        try:
            if module_type == "auto_reply":
                normalized = normalize_auto_reply_button_rows(buttons)
            else:
                normalized = ScheduledMessageValidationMixin.normalize_buttons_config(buttons)
        except ValidationError:
            normalized = cls._fallback_normalize_buttons(buttons, module_type=module_type)
        return [chunk for row in normalized for chunk in cls._chunk_row(row) if chunk]

    @classmethod
    def _fallback_normalize_buttons(
        cls,
        buttons: list,
        *,
        module_type: str | None,
    ) -> list[list[dict[str, str]]]:
        rows = buttons if isinstance(buttons, list) else []
        return [row for raw_row in rows if (row := cls._normalize_raw_row(raw_row, module_type=module_type))]

    @classmethod
    def _normalize_raw_row(cls, raw_row, *, module_type: str | None) -> list[dict[str, str]]:
        if not isinstance(raw_row, list):
            return []
        return [
            value
            for raw_cell in raw_row
            if isinstance(raw_cell, dict)
            if (value := cls._normalize_raw_cell(raw_cell, module_type=module_type)) is not None
        ]

    @classmethod
    def _normalize_raw_cell(cls, raw_cell: dict, *, module_type: str | None) -> dict[str, str] | None:
        text = str(raw_cell.get("text", "")).strip()
        action_type = str(raw_cell.get("action_type", "")).strip()
        payload = str(raw_cell.get("payload", "")).strip()
        if module_type == "auto_reply" and action_type == AUTO_REPLY_TEXT_TRIGGER:
            return {"text": text, "action_type": action_type, "payload": payload} if text and payload else None
        url = str(raw_cell.get("url", raw_cell.get("link", ""))).strip()
        if not text or not url:
            return None
        try:
            return {"text": text, "url": cls.normalize_button_url(url)}
        except ValidationError:
            return None

    @staticmethod
    def _clone_grid(grid: ButtonGrid) -> ButtonGrid:
        return [
            [None if cell is None else ButtonLayoutEditorService._clone_cell(cell) for cell in row]
            for row in grid
        ]

    @staticmethod
    def _clone_cell(cell: dict[str, str]) -> dict[str, str]:
        cloned = {
            "text": str(cell.get("text", "")),
            "url": str(cell.get("url", "")),
        }
        action_type = str(cell.get("action_type", "")).strip()
        payload = str(cell.get("payload", "")).strip()
        if action_type:
            cloned["action_type"] = action_type
        if payload:
            cloned["payload"] = payload
        return cloned

    @staticmethod
    def _cell_from_button(item: dict[str, str]) -> dict[str, str]:
        cell = {
            "text": str(item.get("text", "")),
            "url": str(item.get("url", "")),
        }
        if item.get("action_type") == AUTO_REPLY_TEXT_TRIGGER:
            cell["action_type"] = AUTO_REPLY_TEXT_TRIGGER
            cell["payload"] = str(item.get("payload", ""))
            cell["url"] = ""
        return cell

    @classmethod
    def _trim_grid(cls, grid: ButtonGrid) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        while draft and not any(cell is not None for cell in draft[-1]):
            draft.pop()
        return draft or [[]]

    @staticmethod
    def _set_cell(grid: ButtonGrid, row_index: int, col_index: int, *, value: ButtonCell) -> None:
        while len(grid) <= row_index:
            grid.append([])
        while len(grid[row_index]) <= col_index:
            grid[row_index].append(None)
        grid[row_index][col_index] = value
