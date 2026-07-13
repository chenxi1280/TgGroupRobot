from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from telegram import InlineKeyboardButton


WAITING_VALUE = "【等待设置】"


@dataclass(frozen=True)
class PanelField:
    icon: str
    label: str
    value: str


def is_set(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def summarize_text(value: str | None, *, limit: int = 120, empty: str = WAITING_VALUE) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return empty
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def button_count(buttons: object) -> int:
    if not isinstance(buttons, list):
        return 0
    total = 0
    for row in buttons:
        if isinstance(row, list):
            total += len([item for item in row if isinstance(item, dict)])
    return total


def button_status(buttons: object) -> str:
    count = button_count(buttons)
    return WAITING_VALUE if count <= 0 else f"已设置 {count} 个"


def media_status(*, has_media: bool, media_type: str | None = None) -> str:
    if not has_media:
        return WAITING_VALUE
    if media_type and media_type != "none":
        return f"已设置 {media_type}"
    return "已设置"


def mark_configured(label: str, configured: bool) -> str:
    return f"✅ {label}" if configured else label


def action_button(label: str, callback_data: str, *, configured: bool = False) -> InlineKeyboardButton:
    return InlineKeyboardButton(mark_configured(label, configured), callback_data=callback_data)


def _progress_lines(items: list[tuple[str, bool]]) -> list[str]:
    if not items:
        return []
    done_count = sum(1 for _, done in items if done)
    lines = [f"必填完成: {done_count}/{len(items)}"]
    lines.extend(f"{'✅' if done else '❌'} {label}" for label, done in items)
    return lines


def format_completion_lines(
    required_items: Iterable[tuple[str, bool]],
    *,
    next_step: str | None = None,
    test_step: str | None = None,
) -> list[str]:
    """Build a compact completion guide for multi-step config pages."""
    items = list(required_items)
    if not items and not next_step and not test_step:
        return []

    lines = ["", "配置进度:"]
    lines.extend(_progress_lines(items))
    if next_step:
        lines.append(f"下一步: {next_step}")
    if test_step:
        lines.append(f"测试: {test_step}")
    return lines


def format_panel(title: str, fields: Iterable[PanelField], *, footer: Iterable[str] | None = None, toast: str | None = None) -> str:
    lines: list[str] = []
    if toast:
        lines.extend([toast, ""])
    lines.extend([title, ""])
    for field in fields:
        lines.append(f"{field.icon} {field.label}: {field.value}")
        lines.append("")
    for line in footer or []:
        lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
