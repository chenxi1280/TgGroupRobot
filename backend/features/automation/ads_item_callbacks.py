from __future__ import annotations


import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.services.ad_rotation_service import (
    cleanup_expired_rotation_items,
    create_rotation_item,
    format_local_datetime,
    get_rotation_item,
    list_rotation_items,
    preview_rotation_item,
    update_rotation_item,
)
from backend.features.automation.ui.ads import (
    ads_copy_time_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.shared.button_layout_editor import ButtonEditorContext, show_layout_menu
from backend.shared.time_ui import build_datetime_prompt_text, next_top_of_hour
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
)

from backend.features.automation.ads_context import (
    _ads_handler,
    _parse_ad_id_from_callback,
    _resolve_ads_target_chat_id,
)
from backend.features.automation.ads_rule_callbacks import ads_menu_callback

log = structlog.get_logger(__name__)

async def ads_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    cb = CallbackParser.parse(update.callback_query.data or "")
    page = 0
    for index in range(cb.length() - 1, 0, -1):
        value = cb.get_int_optional(index)
        if value is not None and value >= 0:
            page = value
            break

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_list(update, context, target_chat_id, page=page)


async def ads_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ads_menu_callback(update, context)


async def ads_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return
    await _ads_handler.show_detail(update, context, target_chat_id, item_id)


async def ads_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=target_chat_id,
            chat_type="supergroup",
            title=update.effective_chat.title,
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )
        item = await create_rotation_item(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            title="新轮播消息",
            content="",
        )
        await session.commit()

    await _ads_handler.show_detail(update, context, target_chat_id, item.id)


async def ads_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return
        item.enabled = not item.enabled
        await session.commit()
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    if cb.has_int(4):
        item_id = cb.require_int(4, label="item_id")
        field = cb.get(5)
        value = cb.get(6)
    else:
        item_id = cb.require_int(3, label="item_id")
        field = cb.get(4)
        value = cb.get(5)

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return

        if field == "enabled":
            await update_rotation_item(session, item_id, enabled=value == "1")
        else:
            await session.commit()
            await answer_callback_query_safely(update, "无效操作", show_alert=True)
            return
        await session.commit()
    await _ads_handler.show_detail(update, context, target_chat_id, item_id)


async def ads_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return
        await session.delete(item)
        await session.flush()
        remaining = await list_rotation_items(session, target_chat_id)
        for index, row in enumerate(remaining, start=1):
            row.sort_order = index
        await session.commit()
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    item_id, field = _parse_item_input_target(q.data or "")
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    if field == "buttons":
        await _show_ads_button_editor(update, context, target_chat_id=target_chat_id, item_id=item_id)
        return
    state_type = {
        "title": "ads_item_edit_title",
        "text": "ads_item_edit_text",
        "cover": "ads_item_edit_cover",
        "start": "ads_item_edit_start",
        "end": "ads_item_edit_end",
        "order": "ads_item_edit_order",
    }.get(field)
    if state_type is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return
    await _start_item_input_state(
        update,
        context,
        target_chat_id=target_chat_id,
        item_id=item_id,
        state_type=state_type,
    )
    await _show_item_input_prompt(q, target_chat_id=target_chat_id, item_id=item_id, field=field)


def _parse_item_input_target(data: str) -> tuple[int, str | None]:
    callback = CallbackParser.parse(data)
    if callback.has_int(4):
        return callback.require_int(4, label="item_id"), callback.get(5)
    return callback.require_int(3, label="item_id"), callback.get(4)


async def _show_ads_button_editor(update: Update, context, *, target_chat_id: int, item_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await show_layout_menu(
            update,
            context,
            ButtonEditorContext("ads", target_chat_id, item_id),
            session=session,
        )
        await session.commit()


async def _start_item_input_state(
    update: Update,
    context,
    *,
    target_chat_id: int,
    item_id: int,
    state_type: str,
) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ConversationStateService.start(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id, "item_id": item_id},
        )
        await session.commit()


async def _show_item_input_prompt(query, *, target_chat_id: int, item_id: int, field: str) -> None:
    prompt = {
        "title": "🎠 轮播消息 | 标题备注\n\n请输入标题备注，例如：周末活动通知。\n输入“清空”可恢复默认标题。",
        "text": "🎠 轮播消息 | 文本内容\n\n请输入要轮播发送到群里的正文。\n可以直接发送多行文本，输入“清空”可清空文本。",
        "cover": "👉 请发送图片作为封面；发送“清空”可移除封面。",
        "order": "👉 请输入新的轮播顺序数字，例如 1。",
    }.get(field)
    if field in {"start", "end"}:
        await _show_item_time_prompt(
            query,
            target_chat_id=target_chat_id,
            item_id=item_id,
            field=field,
        )
        return
    await query.edit_message_text(
        prompt or "请输入配置内容。",
        reply_markup=_item_back_keyboard(target_chat_id, item_id),
    )


async def _show_item_time_prompt(query, *, target_chat_id: int, item_id: int, field: str) -> None:
    is_end = field == "end"
    sample_time = next_top_of_hour(days_offset=1) if is_end else next_top_of_hour()
    sample_label = format_local_datetime(sample_time, empty="")
    field_label = "结束" if is_end else "开始"
    await query.edit_message_text(
        build_datetime_prompt_text(
            title=f"🎠 轮播消息 | 编辑{field_label}时间",
            sample_time_text=sample_label,
            sample_time_unix=int(sample_time.timestamp()),
            show_copy_hint=False,
            input_hint=f"👉🏻 现在输入定时{field_label}时间:",
        ),
        parse_mode="HTML",
        reply_markup=ads_copy_time_keyboard(
            f"ads:detail:{target_chat_id}:{item_id}",
            sample_label,
        ),
    )


def _item_back_keyboard(target_chat_id: int, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 返回", callback_data=f"ads:detail:{target_chat_id}:{item_id}")]]
    )


async def ads_item_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    cb = CallbackParser.parse(update.callback_query.data or "")
    item_id = cb.require_int(4, label="item_id") if cb.has_int(4) else cb.require_int(3, label="item_id")
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_time_range(update, context, target_chat_id, item_id=item_id)


async def ads_cleanup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        deleted = await cleanup_expired_rotation_items(session, target_chat_id)
        await session.commit()
    await answer_callback_query_safely(update, f"已清理 {deleted} 条过期轮播", show_alert=False)
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()

    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        await session.commit()
    if item is None or item.chat_id != target_chat_id:
        await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
        return

    await preview_rotation_item(context, chat_id=update.effective_user.id, item=item)
    await answer_callback_query_safely(update, "预览已发送到当前私聊", show_alert=False)


async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ads_item_preview_callback(update, context)
