from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_create import auto_reply_create_start_impl
from backend.features.moderation.auto_reply_helpers import (
    _ensure_callback_update,
    _resolve_auto_reply_target_chat_id,
    _format_auto_reply_rule_detail,
    _parse_auto_reply_buttons_input,
    _send_auto_reply_payload,
    _show_auto_reply_delay_page,
    _show_auto_reply_rule_detail,
    _extract_auto_reply_list_page,
    _render_auto_reply_list,
)
from backend.features.moderation.auto_reply_input import auto_reply_config_handler, auto_reply_message_handler
from backend.features.moderation.auto_reply_menu import _auto_reply_menu_handler
from backend.features.moderation.auto_reply_delete import _auto_reply_delete_handler
from backend.features.moderation.auto_reply_delete_actions import (
    auto_reply_delete_confirm_action,
    auto_reply_delete_do_action,
)
from backend.features.moderation.auto_reply_detail_actions import (
    auto_reply_detail_action,
    auto_reply_preview_action,
)
from backend.features.moderation.auto_reply_edit_actions import (
    auto_reply_edit_action,
    auto_reply_rule_config_action,
)
from backend.features.moderation.auto_reply_order_actions import auto_reply_move_action
from backend.features.moderation.auto_reply_cancel import auto_reply_cancel_callback
from backend.features.moderation.auto_reply_toggle import _auto_reply_toggle_handler
from backend.features.moderation.services.auto_reply_service import (
    delete_auto_reply_rule,
    get_auto_reply_enable_error,
    get_auto_reply_rule_in_chat,
    move_auto_reply_rule,
    toggle_auto_reply_rule,
    update_auto_reply_rule,
)
from backend.platform.state.state_service import set_user_state

async def auto_reply_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复菜单回调（适配器函数）"""
    await _auto_reply_menu_handler.handle_callback(update, context)


async def auto_reply_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复规则列表回调"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await q.answer()

    await _render_auto_reply_list(
        update,
        context,
        target_chat_id=target_chat_id,
        page=_extract_auto_reply_list_page(q.data),
    )


async def auto_reply_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_create_start_impl(update, context)


async def auto_reply_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_detail_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        show_rule_detail_func=_show_auto_reply_rule_detail,
    )


async def auto_reply_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_preview_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        send_auto_reply_payload_func=_send_auto_reply_payload,
    )


async def auto_reply_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_edit_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        set_user_state_func=set_user_state,
    )


async def auto_reply_rule_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_rule_config_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        update_rule_func=update_auto_reply_rule,
        show_rule_detail_func=_show_auto_reply_rule_detail,
    )


async def auto_reply_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 6:
        await q.answer("无效配置项", show_alert=True)
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("规则不存在", show_alert=True)
        return

    field = parts[4]
    value = parts[5]

    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, target_chat_id, rule_id)
        if rule is None:
            await session.commit()
            await q.answer("规则不存在", show_alert=True)
            return

        updates: dict[str, object] = {}
        if field == "active":
            if value not in {"0", "1"}:
                await session.commit()
                await q.answer("状态配置无效", show_alert=True)
                return
            enabled = value == "1"
            if enabled:
                enable_error = get_auto_reply_enable_error(rule)
                if enable_error is not None:
                    await session.commit()
                    await q.answer(enable_error, show_alert=True)
                    return
            updates["is_active"] = enabled
        elif field == "match":
            if value not in {"exact", "contains"}:
                await session.commit()
                await q.answer("匹配方式无效", show_alert=True)
                return
            updates["match_type"] = value
        elif field == "source":
            if value not in {"0", "1"}:
                await session.commit()
                await q.answer("删除来源配置无效", show_alert=True)
                return
            updates["delete_source"] = value == "1"
        else:
            await session.commit()
            await q.answer("无效配置项", show_alert=True)
            return

        await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, **updates)
        await session.commit()

    await q.answer("已更新")
    if _is_auto_reply_list_message(update):
        await _render_auto_reply_list(update, context, target_chat_id=target_chat_id, page=0)
    else:
        await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_delay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 4:
        await q.answer("规则不存在", show_alert=True)
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("规则不存在", show_alert=True)
        return

    await q.answer()
    await _show_auto_reply_delay_page(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_delay_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context, chat_index=3)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 6:
        await q.answer("延迟删除配置无效", show_alert=True)
        return
    try:
        rule_id = int(parts[4])
        delay_seconds = int(parts[5])
    except ValueError:
        await q.answer("延迟删除配置无效", show_alert=True)
        return
    if delay_seconds not in {0, 15, 30, 60, 90}:
        await q.answer("延迟删除配置无效", show_alert=True)
        return

    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, target_chat_id, rule_id)
        if rule is None:
            await session.commit()
            await q.answer("规则不存在", show_alert=True)
            return
        await update_auto_reply_rule(
            session,
            rule_id,
            chat_id=target_chat_id,
            delete_reply_delay_seconds=delay_seconds,
        )
        await session.commit()

    await q.answer("已更新")
    await _show_auto_reply_delay_page(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_move_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        move_rule_func=move_auto_reply_rule,
        render_list_func=_render_auto_reply_list,
    )


async def auto_reply_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_delete_confirm_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
    )


async def auto_reply_delete_do_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_delete_do_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        delete_rule_func=delete_auto_reply_rule,
        render_list_func=_render_auto_reply_list,
    )


# Handler 类定义（使用 BaseHandler）

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换自动回复规则状态回调（兼容新旧格式）"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    data = q.data or ""
    if data.startswith("auto_reply:toggle:"):
        target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
        if target_chat_id is None:
            return
        parts = data.split(":")
        if len(parts) < 4:
            await q.answer("规则不存在", show_alert=True)
            return
        try:
            rule_id = int(parts[3])
        except ValueError:
            await q.answer("规则不存在", show_alert=True)
            return

        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rule = await get_auto_reply_rule_in_chat(session, target_chat_id, rule_id)
            if rule is None:
                await session.commit()
                await q.answer("规则不存在", show_alert=True)
                return
            if not rule.is_active:
                enable_error = get_auto_reply_enable_error(rule)
                if enable_error is not None:
                    await session.commit()
                    await q.answer(enable_error, show_alert=True)
                    return
            success = await toggle_auto_reply_rule(session, rule_id, chat_id=target_chat_id)
            await session.commit()

        if not success:
            await q.answer("规则不存在", show_alert=True)
            return

        await q.answer("状态已切换")
        if _is_auto_reply_list_message(update):
            await _render_auto_reply_list(update, context, target_chat_id=target_chat_id, page=0)
        else:
            await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)
        return

    await _auto_reply_toggle_handler.handle_callback(update, context, require_admin=False)


# 适配器函数（保持 Router 兼容）
async def auto_reply_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除自动回复规则回调（适配器函数）"""
    await _auto_reply_delete_handler.handle_callback(update, context)


def _is_auto_reply_list_message(update: Update) -> bool:
    message = getattr(update.callback_query, "message", None) if update.callback_query else None
    text = getattr(message, "text", None) or ""
    return text.startswith("💬 自动回复\n\n可用于设置")


# ============================================
# 消息处理器
# ============================================
