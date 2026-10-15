"""Compact opt-in admin settings; published and user-authored keyboards bypass this."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import unicodedata

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# About fourteen Chinese characters fit comfortably in half a mobile keyboard.
HALF_ROW_WIDTH = 28
OPTION_COLUMNS = 2
BOUNDARY_LABELS = ('返回', '取消', '删除', '清空', '执行导入', '执行克隆', '确认', '上一页', '下一页')


def _width(text: str) -> int:
    return sum(0 if unicodedata.combining(c) or c in '\ufe0f\u200d' else
        2 if unicodedata.east_asian_width(c) in {'W', 'F'} else 1 for c in text)


def _compact_option(button: InlineKeyboardButton) -> bool:
    text = button.text
    callback = button.callback_data
    return (isinstance(callback, str) and bool(callback) and callback != '_noop'
        and 'noop' not in callback.split(':') and not button.url
        and _width(text) <= HALF_ROW_WIDTH and not text.endswith(('：', ':'))
        and not text.startswith('·')
        and not any(word in text for word in BOUNDARY_LABELS))


def _with_navigation(rows):
    source = [list(row) for row in rows]
    index = 0
    while index < len(source):
        row = source[index]
        following = source[index + 1] if index + 1 < len(source) else []
        footer = (len(row) == len(following) == 1 and '刷新' in row[0].text
            and '返回' in following[0].text)
        yield row + following if footer else row
        index += OPTION_COLUMNS if footer else 1


def admin_keyboard(rows: Iterable[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Pair short options while preserving explicit groups, order and button data.

    Existing multi-button rows, navigation, descriptions and dangerous operations
    are barriers. Button objects and caller-owned rows are never changed.
    """
    result: list[list[InlineKeyboardButton]] = []
    pending: list[InlineKeyboardButton] = []
    for row in _with_navigation(rows):
        if len(row) == 1 and _compact_option(row[0]):
            pending.extend(row)
            if len(pending) == OPTION_COLUMNS:
                result.append(pending)
                pending = []
        else:
            if pending:
                result.append(pending)
                pending = []
            result.append(row)
    if pending:
        result.append(pending)
    return InlineKeyboardMarkup(result)
