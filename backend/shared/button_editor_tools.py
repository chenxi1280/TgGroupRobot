"""Private editor utilities, called only after the editor's permission check."""
import io
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.button_layout_persistence import _ensure_draft, ensure_message_draft
from backend.shared.button_layout_service import ButtonLayoutEditorService
from backend.shared.button_layout_views import detail_callback_data
from backend.shared.ui.copy import COPY_TEXT_LIMIT, copy_value_rows
from backend.shared.services.base import ValidationError


async def show_input(request, prompt: str, *, field: str, return_action: str) -> None:
    if field == "body":
        record = await ensure_message_draft(request.session, request.context, request.editor_ctx)
        value = record.state_data["message"].get("text") or ""
    else:
        grid = await _ensure_draft(request.session, request.context, request.editor_ctx)
        cell = ButtonLayoutEditorService.get_cell(grid, request.editor_ctx.row_index or 0, request.editor_ctx.col_index or 0)
        value = (cell or {}).get(field) or ""
    current = value[:COPY_TEXT_LIMIT] + ("…（完整内容可导出）" if len(value) > COPY_TEXT_LIMIT else "")
    rows = copy_value_rows([("复制当前值", value)])
    export = "export_body" if field == "body" else "export_buttons"
    rows.append([InlineKeyboardButton("导出当前内容", callback_data=detail_callback_data(request.editor_ctx, export))])
    rows.append([InlineKeyboardButton("取消输入", callback_data=detail_callback_data(request.editor_ctx, return_action))])
    await request.update.callback_query.edit_message_text(
        f"{prompt}\n\n当前值：{current or '未配置'}\n仅修改草稿，保存后生效；复制后需粘贴修改并发送。",
        reply_markup=InlineKeyboardMarkup(rows))


async def export_draft(request) -> None:
    if request.update.effective_chat.type != "private":
        raise ValidationError("请在私聊中导出配置。")
    record = await ensure_message_draft(request.session, request.context, request.editor_ctx)
    if request.action == "export_body":
        content, filename = record.state_data["message"].get("text") or "", "message.txt"
    else:
        grid = await _ensure_draft(request.session, request.context, request.editor_ctx)
        content, filename = json.dumps(grid, ensure_ascii=False, indent=2), "buttons.json"
    if not content:
        await request.update.effective_message.reply_text("当前正文为空，无需导出。")
        return
    document = io.BytesIO(content.encode("utf-8"))
    await request.update.effective_message.reply_document(document, filename=filename,
        caption="当前草稿原文，可下载复制编辑；导出不会保存或发布。")


async def confirm_clear(request) -> None:
    await request.update.callback_query.edit_message_text(
        "确认清空当前草稿中的全部按钮？正文和封面保留，保存后才影响正式配置。",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("取消", callback_data=detail_callback_data(request.editor_ctx, "open")),
            InlineKeyboardButton("确认清空按钮", callback_data=detail_callback_data(request.editor_ctx, "clear_confirm")),
        ]]))
