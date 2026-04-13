from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def auto_reply_delete_confirm_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    get_rule_in_chat_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.edit_message_text("删除失败")
        await q.answer()
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("删除失败")
        await q.answer()
        return

    from backend.features.moderation.ui.auto_reply import auto_reply_delete_confirm_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_rule_in_chat_func(session, target_chat_id, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != target_chat_id:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return

    text = "\n".join([
        "⚠️ 确认删除自动回复规则？",
        "",
        f"规则 #{rule.sort_order} [{rule.id}]",
        f"关键词: {', '.join(rule.keywords)}",
        "",
        "删除后将不再参与匹配。",
    ])
    await q.edit_message_text(
        text,
        reply_markup=auto_reply_delete_confirm_keyboard(rule.id, target_chat_id),
    )
    await q.answer()


async def auto_reply_delete_do_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    delete_rule_func,
    render_list_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.edit_message_text("删除失败")
        await q.answer()
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("删除失败")
        await q.answer()
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_rule_func(session, rule_id, chat_id=target_chat_id)
        await session.commit()

    if not success:
        await q.answer("删除失败", show_alert=True)
        return

    await q.answer("规则已删除")
    await render_list_func(update, context, target_chat_id=target_chat_id, page=0)
