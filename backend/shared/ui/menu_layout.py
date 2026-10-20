"""Explicit semantic sections for administrative keyboards.

Callers decide whether a button is an action, a record, or a destructive action.
No text matching and no reflow of user-authored publish keyboards.
"""
from collections.abc import Sequence
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8


def action_rows(buttons: Sequence[InlineKeyboardButton], *, columns: int = 2):
    return [list(buttons[index:index + columns]) for index in range(0, len(buttons), columns)]


def navigation_row(back: str, *, refresh: str | None = None):
    row = [InlineKeyboardButton("🔙 返回", callback_data=back)]
    if refresh:
        row.append(InlineKeyboardButton("刷新", callback_data=refresh))
    return row


def menu_keyboard(*sections) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(row) for section in sections for row in section if row])


def page_slice(items, page: int):
    total = len(items)
    page = min(max(0, page), max(0, (total - 1) // PAGE_SIZE))
    return items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], total, page


def page_navigation(page: int, total: int, callback):
    buttons = []
    if page:
        buttons.append(InlineKeyboardButton("上一页", callback_data=callback(page - 1)))
    if (page + 1) * PAGE_SIZE < total:
        buttons.append(InlineKeyboardButton("下一页", callback_data=callback(page + 1)))
    return [buttons] if buttons else []
