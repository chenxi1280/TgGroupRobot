from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.button_layout_persistence import (
    _ensure_draft,
    _module_return_callback,
    _module_title,
)
from backend.shared.button_layout_service import (
    AUTO_REPLY_TEXT_TRIGGER,
    ButtonEditorContext,
    ButtonGrid,
    ButtonLayoutEditorService,
)
from backend.shared.services.base import ValidationError


def _item_callback_data(editor_ctx: ButtonEditorContext, item: dict[str, Any]) -> str:
    kind = item["kind"]
    if kind == "cell":
        action = "detail"
    elif kind in {"add", "empty"}:
        action = "add"
    else:
        return "btned:noop"
    return (
        f"btned:{action}:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:"
        f"{item['row']}:{item['col']}"
    )


def _build_layout_row(
    editor_ctx: ButtonEditorContext,
    row: list[dict[str, Any]],
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            str(item["label"]),
            callback_data=_item_callback_data(editor_ctx, item),
        )
        for item in row
    ]


def build_layout_keyboard(editor_ctx: ButtonEditorContext, grid: ButtonGrid) -> InlineKeyboardMarkup:
    rows = [
        _build_layout_row(editor_ctx, row)
        for row in ButtonLayoutEditorService.display_rows(grid)
    ]
    rows.append([
        InlineKeyboardButton(
            "♻️ 清空按钮",
            callback_data=(
                f"btned:clear:{editor_ctx.module_type}:"
                f"{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"
            ),
        ),
        InlineKeyboardButton("🔙 返回", callback_data=_module_return_callback(editor_ctx)),
    ])
    return InlineKeyboardMarkup(rows)


def detail_callback_data(
    editor_ctx: ButtonEditorContext,
    action: str,
    *,
    extra: str | None = None,
) -> str:
    callback_data = (
        f"btned:{action}:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:"
        f"{editor_ctx.entity_id}:{editor_ctx.row_index or 0}:{editor_ctx.col_index or 0}"
    )
    return f"{callback_data}:{extra}" if extra else callback_data


def _detail_action_button(
    editor_ctx: ButtonEditorContext,
    label: str,
    action: str,
    *,
    extra: str | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        label,
        callback_data=detail_callback_data(editor_ctx, action, extra=extra),
    )


def build_detail_keyboard(editor_ctx: ButtonEditorContext) -> InlineKeyboardMarkup:
    rows = [[
        _detail_action_button(editor_ctx, "编辑按钮文字", "text"),
        _detail_action_button(editor_ctx, "编辑跳转链接", "url"),
    ]]
    if editor_ctx.module_type == "auto_reply":
        rows.append([_detail_action_button(editor_ctx, "编辑触发文字", "payload")])
    rows.extend([
        [_detail_action_button(editor_ctx, "⬆️ 上移", "move", extra="up")],
        [
            _detail_action_button(editor_ctx, "⬅️ 左移", "move", extra="left"),
            _detail_action_button(editor_ctx, "➡️ 右移", "move", extra="right"),
        ],
        [
            _detail_action_button(editor_ctx, "⬇️ 下移", "move", extra="down"),
            _detail_action_button(editor_ctx, "❌ 删除按钮", "delete"),
        ],
        [InlineKeyboardButton(
            "🔙 返回",
            callback_data=(
                f"btned:open:{editor_ctx.module_type}:"
                f"{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"
            ),
        )],
    ])
    return InlineKeyboardMarkup(rows)


async def _reply_or_edit(
    update: Update,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(text=text, reply_markup=reply_markup)


async def _render_layout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    editor_ctx: ButtonEditorContext,
    session,
) -> None:
    draft = await _ensure_draft(session, context, editor_ctx)
    text = (
        f"{_module_title(editor_ctx.module_type)}｜按钮布局\n\n"
        "先配置按钮布局（每行最多4个按钮） 再点击按钮配置文案"
    )
    await _reply_or_edit(
        update,
        text=text,
        reply_markup=build_layout_keyboard(editor_ctx, draft),
    )


async def show_layout_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    *,
    session=None,
) -> None:
    if session is not None:
        await _render_layout(update, context, editor_ctx=editor_ctx, session=session)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as owned_session:
        await _render_layout(update, context, editor_ctx=editor_ctx, session=owned_session)
        await owned_session.commit()


def _detail_text(module_type: str, cell: dict[str, str]) -> str:
    action_label = "触发文字" if cell.get("action_type") == AUTO_REPLY_TEXT_TRIGGER else "跳转链接"
    return (
        f"{_module_title(module_type)} | 编辑按钮信息\n\n"
        f"按钮文字：{cell.get('text') or '未配置'}\n"
        f"按钮类型：{action_label}\n"
        f"按钮链接：{cell.get('url') or '未配置'}\n"
        f"触发文字：{cell.get('payload') or '未配置'}\n\n"
        "💡 为了按钮美观，建议按钮文字不超过 4 个字\n"
        "🔗 链接请填写完整；触发文字可填写“签到”“积分”“积分排行”等群内文字入口。\n"
        "提示：填写“签到”时依赖积分中心开启签到；未开启时用户点击会提示“本群未开启签到”。"
    )


async def _render_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    editor_ctx: ButtonEditorContext,
    session,
) -> None:
    draft = await _ensure_draft(session, context, editor_ctx)
    cell = ButtonLayoutEditorService.get_cell(
        draft,
        int(editor_ctx.row_index or 0),
        int(editor_ctx.col_index or 0),
    )
    if cell is None:
        raise ValidationError("按钮不存在。")
    await _reply_or_edit(
        update,
        text=_detail_text(editor_ctx.module_type, cell),
        reply_markup=build_detail_keyboard(editor_ctx),
    )


async def show_button_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    *,
    session=None,
) -> None:
    if session is not None:
        await _render_detail(update, context, editor_ctx=editor_ctx, session=session)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as owned_session:
        await _render_detail(update, context, editor_ctx=editor_ctx, session=owned_session)
        await owned_session.commit()
