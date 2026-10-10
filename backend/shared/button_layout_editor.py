from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_buttons import sanitize_text_trigger_payload
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.button_layout_persistence import (
    _ensure_draft,
    _module_capability,
    _module_title,
    _persist_draft,
    _save_buttons_for_module,
    save_button_draft, discard_button_draft,
    ensure_message_draft,
)
from backend.shared.button_layout_service import (
    AUTO_REPLY_TEXT_TRIGGER,
    ButtonEditorContext,
    ButtonGrid,
    ButtonLayoutEditorService,
    PAYLOAD_INPUT_STATE,
    TEXT_INPUT_STATE,
    URL_INPUT_STATE,
)
from backend.shared.button_layout_views import (
    build_detail_keyboard as build_detail_keyboard,
    build_layout_keyboard as build_layout_keyboard,
    detail_callback_data,
    show_button_detail,
    show_layout_menu,
)
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.ui.button_input import is_clear_button_input

@dataclass(frozen=True, slots=True)
class EditorCallbackRequest:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: Any
    action: str
    editor_ctx: ButtonEditorContext
    extra: str | None

EditorAction = Callable[[EditorCallbackRequest], Awaitable[None]]

def _parse_editor_context(callback_data: str) -> tuple[str, ButtonEditorContext, str | None]:
    cb = CallbackParser.parse(callback_data)
    editor_ctx = ButtonEditorContext(
        cb.get(2),
        cb.get_int(3),
        cb.get_int(4),
        cb.get_int_optional(5),
        cb.get_int_optional(6),
    )
    return cb.get(1), editor_ctx, cb.get(7)

async def _persist_editor_draft(request: EditorCallbackRequest, grid: ButtonGrid) -> None:
    await _persist_draft(
        request.session,
        request.context,
        request.editor_ctx,
        grid=grid,
        save_buttons=_save_buttons_for_module,
    )

async def _open_layout(request: EditorCallbackRequest) -> None:
    await show_layout_menu(
        request.update,
        request.context,
        request.editor_ctx,
        session=request.session,
    )


async def _add_button(request: EditorCallbackRequest) -> None:
    draft = await _ensure_draft(request.session, request.context, request.editor_ctx)
    next_grid, row, col = ButtonLayoutEditorService.add_button(
        draft,
        row_index=request.editor_ctx.row_index,
        col_index=request.editor_ctx.col_index,
    )
    await _persist_editor_draft(request, next_grid)
    detail_ctx = ButtonEditorContext(
        request.editor_ctx.module_type,
        request.editor_ctx.target_chat_id,
        request.editor_ctx.entity_id,
        row,
        col,
    )
    await show_button_detail(
        request.update,
        request.context,
        detail_ctx,
        session=request.session,
    )


async def _clear_buttons(request: EditorCallbackRequest) -> None:
    await _persist_editor_draft(request, ButtonLayoutEditorService.clear_buttons())
    await _open_layout(request)


async def _show_detail(request: EditorCallbackRequest) -> None:
    await show_button_detail(
        request.update,
        request.context,
        request.editor_ctx,
        session=request.session,
    )


def _input_prompt(action: str) -> str:
    if action == "text":
        return "👉 请输入按钮文字；发送“清空”可暂时留空。"
    if action == "payload":
        return (
            "👉 请输入触发文字，例如：签到、积分、积分排行、积分商城。发送“清空”可暂时留空。\n\n"
            "提示：如果填写“签到”，需要先在积分中心开启签到；未开启时用户点击会提示“本群未开启签到”。"
        )
    return "👉 请输入跳转链接；发送“清空”可暂时留空。"


def _editor_state_data(editor_ctx: ButtonEditorContext) -> dict[str, str | int | None]:
    return {
        "module_type": editor_ctx.module_type,
        "target_chat_id": editor_ctx.target_chat_id,
        "entity_id": editor_ctx.entity_id,
        "row_index": editor_ctx.row_index,
        "col_index": editor_ctx.col_index,
    }


async def _start_input(request: EditorCallbackRequest) -> None:
    state_type = {
        "text": TEXT_INPUT_STATE,
        "url": URL_INPUT_STATE,
        "payload": PAYLOAD_INPUT_STATE,
    }[request.action]
    update = request.update
    await ConversationStateService.start(
        request.session,
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        state_type=state_type,
        state_data=_editor_state_data(request.editor_ctx),
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔙 返回",
            callback_data=detail_callback_data(request.editor_ctx, "detail"),
        )
    ]])
    await update.callback_query.edit_message_text(
        text=(
            f"{_module_title(request.editor_ctx.module_type)} | 编辑按钮信息\n\n"
            f"{_input_prompt(request.action)}"
        ),
        reply_markup=keyboard,
    )


async def _delete_button(request: EditorCallbackRequest) -> None:
    draft = await _ensure_draft(request.session, request.context, request.editor_ctx)
    next_grid = ButtonLayoutEditorService.delete_button(
        draft,
        int(request.editor_ctx.row_index or 0),
        int(request.editor_ctx.col_index or 0),
    )
    await _persist_editor_draft(request, next_grid)
    await _open_layout(request)


async def _move_button(request: EditorCallbackRequest) -> None:
    draft = await _ensure_draft(request.session, request.context, request.editor_ctx)
    next_grid, row, col, changed = ButtonLayoutEditorService.move_button(
        draft,
        int(request.editor_ctx.row_index or 0),
        int(request.editor_ctx.col_index or 0),
        direction=str(request.extra or ""),
    )
    await _persist_editor_draft(request, next_grid)
    if not changed:
        await answer_callback_query_safely(request.update, "已经到边界了", show_alert=False)
    detail_ctx = ButtonEditorContext(
        request.editor_ctx.module_type,
        request.editor_ctx.target_chat_id,
        request.editor_ctx.entity_id,
        row,
        col,
    )
    await show_button_detail(
        request.update,
        request.context,
        detail_ctx,
        session=request.session,
    )


async def _save_layout(request):
    await save_button_draft(request.session, request.context, request.editor_ctx)
    await request.session.commit()
    await answer_callback_query_safely(request.update, "已保存消息配置")
    await _open_layout(request)


async def _discard_layout(request):
    if request.action == "discard_confirm":
        await discard_button_draft(request.session, request.context, request.editor_ctx)
        await _open_layout(request)
        return
    await request.update.callback_query.edit_message_text("确认放弃正文、封面和按钮修改，并重新载入正式版本？",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("确认放弃修改", callback_data=detail_callback_data(request.editor_ctx, "discard_confirm"))],
            [InlineKeyboardButton("返回草稿", callback_data=detail_callback_data(request.editor_ctx, "open"))]]))


async def _preview_layout(request):
    from backend.shared.message_editor_adapter import message_adapter, validate_message_snapshot
    record = await ensure_message_draft(request.session, request.context, request.editor_ctx)
    snapshot = record.state_data["message"]
    validate_message_snapshot(snapshot, message_adapter(request.editor_ctx))
    grid = await _ensure_draft(request.session, request.context, request.editor_ctx)
    buttons = ButtonLayoutEditorService.export_complete_buttons(grid, module_type=request.editor_ctx.module_type)
    rows = []
    for row in buttons:
        rows.append([InlineKeyboardButton(cell["text"], url=cell["url"]) if cell.get("url") else
            InlineKeyboardButton(cell["text"] + "（预览）", callback_data="btned:noop") for cell in row])
    text = snapshot["text"]
    parse_mode = None
    if request.editor_ctx.module_type == "welcome":
        from backend.features.verification.welcome_templates import render_welcome_template
        text = render_welcome_template(text, default_text=text, member=request.update.effective_user,
            group_name=str(request.editor_ctx.target_chat_id), user_id=request.update.effective_user.id)
        parse_mode = "HTML"
    elif request.editor_ctx.module_type == "invite":
        try:
            text = text.format(inviter="测试邀请人", invitee="测试新成员", group=str(request.editor_ctx.target_chat_id))
        except (KeyError, ValueError, IndexError) as exc:
            raise ValidationError("模板变量不支持，请使用 {inviter}、{invitee}、{group}。") from exc
    validate_message_snapshot({**snapshot, "text": text}, message_adapter(request.editor_ctx))
    markup = InlineKeyboardMarkup(rows) if rows else None
    message = request.update.effective_message
    if snapshot.get("media"):
        if snapshot["media_type"] == "video":
            await message.reply_video(snapshot["media"], caption=text, reply_markup=markup, parse_mode=parse_mode)
        else:
            await message.reply_photo(snapshot["media"], caption=text, reply_markup=markup, parse_mode=parse_mode)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode=parse_mode)


async def _start_message_field(request):
    from backend.shared.message_editor_adapter import message_adapter
    await ensure_message_draft(request.session, request.context, request.editor_ctx)
    await ConversationStateService.start(request.session, chat_id=request.update.effective_chat.id,
        user_id=request.update.effective_user.id, state_type=TEXT_INPUT_STATE,
        state_data={**_editor_state_data(request.editor_ctx), "message_field": request.action})
    media_types = message_adapter(request.editor_ctx).media_types
    prompt = "发送新的正文。变量规则沿用原功能。" if request.action == "body" else (
        "发送图片" + ("或视频" if "video" in media_types else "（本功能不支持视频）") + "；发送 清除 可移除封面。")
    await request.update.callback_query.edit_message_text(prompt + "\n仅修改草稿，保存后生效。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回编辑面板", callback_data=detail_callback_data(request.editor_ctx, "open"))]]))


EDITOR_ACTIONS: dict[str, EditorAction] = {
    "body": _start_message_field,
    "cover": _start_message_field,
    "open": _open_layout,
    "save": _save_layout,
    "discard": _discard_layout,
    "discard_confirm": _discard_layout,
    "preview": _preview_layout,
    "add": _add_button,
    "clear": _clear_buttons,
    "detail": _show_detail,
    "text": _start_input,
    "url": _start_input,
    "payload": _start_input,
    "delete": _delete_button,
    "move": _move_button,
}


async def _has_callback_permission(
    request: EditorCallbackRequest,
) -> tuple[bool, str | None]:
    return await PermissionPolicyService.require_manage(
        request.context,
        request.editor_ctx.target_chat_id,
        request.update.effective_user.id,
        capability=_module_capability(request.editor_ctx.module_type),
    )


async def button_layout_editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    from backend.platform.telegram.errors import mark_callback_query_answered
    mark_callback_query_answered(update)
    context.user_data["button_editor_user_id"] = update.effective_user.id
    if update.callback_query.data == "btned:noop":
        return
    action, editor_ctx, extra = _parse_editor_context(update.callback_query.data or "")
    handler = EDITOR_ACTIONS.get(action)
    if handler is None:
        await answer_callback_query_safely(update, "无效操作", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        request = EditorCallbackRequest(update, context, session, action, editor_ctx, extra)
        allowed, error_text = await _has_callback_permission(request)
        if not allowed:
            await answer_callback_query_safely(update, error_text or "没有权限", show_alert=True)
            return
        try:
            if action in {"open", "detail", "save", "discard", "discard_confirm", "preview"}:
                await ConversationStateService.clear(session, update.effective_chat.id, update.effective_user.id)
            await handler(request)
            await session.commit()
        except ValidationError as exc:
            await session.rollback()
            await answer_callback_query_safely(update, str(exc), show_alert=True)


def _editor_context_from_state(state) -> ButtonEditorContext:
    data = state.state_data or {}
    return ButtonEditorContext(
        module_type=str(data.get("module_type") or ""),
        target_chat_id=int(data.get("target_chat_id") or 0),
        entity_id=int(data.get("entity_id") or 0),
        row_index=int(data.get("row_index") or 0),
        col_index=int(data.get("col_index") or 0),
    )


@dataclass(frozen=True, slots=True)
class InputMutation:
    editor_ctx: ButtonEditorContext
    draft: ButtonGrid
    message_text: str


def _update_button_text(mutation: InputMutation) -> ButtonGrid:
    normalized = mutation.message_text.strip()
    value = "" if is_clear_button_input(normalized) else ButtonLayoutEditorService.sanitize_button_text(normalized)
    return ButtonLayoutEditorService.update_button(
        mutation.draft,
        int(mutation.editor_ctx.row_index or 0),
        int(mutation.editor_ctx.col_index or 0),
        text=value,
    )


def _update_button_url(mutation: InputMutation) -> ButtonGrid:
    normalized = mutation.message_text.strip()
    value = "" if is_clear_button_input(normalized) else ButtonLayoutEditorService.normalize_button_url(normalized)
    return ButtonLayoutEditorService.update_button(
        mutation.draft,
        int(mutation.editor_ctx.row_index or 0),
        int(mutation.editor_ctx.col_index or 0),
        url=value,
        action_type="",
        payload="",
    )


def _update_button_payload(mutation: InputMutation) -> ButtonGrid:
    if mutation.editor_ctx.module_type != "auto_reply":
        raise ValidationError("当前模块不支持触发文字。")
    normalized = mutation.message_text.strip()
    value = "" if is_clear_button_input(normalized) else sanitize_text_trigger_payload(normalized)
    return ButtonLayoutEditorService.update_button(
        mutation.draft,
        int(mutation.editor_ctx.row_index or 0),
        int(mutation.editor_ctx.col_index or 0),
        url="",
        action_type=AUTO_REPLY_TEXT_TRIGGER if value else "",
        payload=value,
    )


def _updated_grid_for_input(
    state_type: str,
    editor_ctx: ButtonEditorContext,
    *,
    draft: ButtonGrid,
    message_text: str,
) -> ButtonGrid:
    handlers = {
        TEXT_INPUT_STATE: _update_button_text,
        URL_INPUT_STATE: _update_button_url,
        PAYLOAD_INPUT_STATE: _update_button_payload,
    }
    handler = handlers.get(state_type)
    if handler is None:
        raise ValidationError("当前状态不支持按钮编辑。")
    return handler(InputMutation(editor_ctx, draft, message_text or ""))


async def _clear_editor_state(session, state, user_id: int) -> None:
    await ConversationStateService.clear(session, state.chat_id, user_id)
    if state.chat_id != user_id:
        await ConversationStateService.clear(session, user_id, user_id)


async def _has_input_permission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
) -> tuple[bool, str | None]:
    return await PermissionPolicyService.require_manage(
        context,
        editor_ctx.target_chat_id,
        update.effective_user.id,
        capability=_module_capability(editor_ctx.module_type),
    )


async def _apply_editor_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    editor_ctx: ButtonEditorContext,
    state,
    message_text: str,
) -> None:
    field = (state.state_data or {}).get("message_field")
    if field in {"body", "cover"}:
        from backend.shared.message_editor_adapter import apply_message_input
        await apply_message_input(update, context, session, editor_ctx=editor_ctx, state=state, message_text=message_text)
        await _clear_editor_state(session, state, update.effective_user.id)
        return
    draft = await _ensure_draft(session, context, editor_ctx)
    cell = ButtonLayoutEditorService.get_cell(
        draft,
        int(editor_ctx.row_index or 0),
        int(editor_ctx.col_index or 0),
    )
    if cell is None:
        raise ValidationError("按钮不存在。")
    next_grid = _updated_grid_for_input(
        state.state_type,
        editor_ctx,
        draft=draft,
        message_text=message_text,
    )
    await _persist_draft(
        session,
        context,
        editor_ctx,
        grid=next_grid,
        save_buttons=_save_buttons_for_module,
    )
    await _clear_editor_state(session, state, update.effective_user.id)


async def handle_button_layout_editor_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    context.user_data["button_editor_user_id"] = update.effective_user.id
    editor_ctx = _editor_context_from_state(state)
    editing_message = bool((state.state_data or {}).get("message_field"))
    if not editor_ctx.module_type or editor_ctx.target_chat_id == 0:
        await update.effective_message.reply_text("按钮配置上下文已失效，请重新进入。")
        return
    allowed, error_text = await _has_input_permission(update, context, editor_ctx)
    if not allowed:
        await update.effective_message.reply_text(error_text or "没有权限")
        return
    try:
        await _apply_editor_input(
            update, context, session, editor_ctx=editor_ctx,
            state=state, message_text=message_text,
        )
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        await update.effective_message.reply_text(str(exc))
        return
    if editing_message:
        await show_layout_menu(update, context, editor_ctx, session=session)
    else:
        await show_button_detail(update, context, editor_ctx, session=session)
