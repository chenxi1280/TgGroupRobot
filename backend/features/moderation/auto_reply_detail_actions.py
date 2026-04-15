from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def auto_reply_detail_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    show_rule_detail_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 4:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return

    await q.answer()
    await show_rule_detail_func(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_preview_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    get_rule_in_chat_func,
    send_auto_reply_payload_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 4:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return

    from backend.features.moderation.ui.auto_reply import auto_reply_preview_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_rule_in_chat_func(session, target_chat_id, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != target_chat_id:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return

    if not str(getattr(rule, "reply_content", "") or "").strip():
        await q.answer("请先配置文本内容", show_alert=True)
        return

    await q.answer()
    if getattr(rule, "cover_media_file_id", None):
        await send_auto_reply_payload_func(
            context,
            chat_id=update.effective_chat.id,
            text=rule.reply_content,
            rule=rule,
        )
        await q.edit_message_text(
            "👁️ 预览已发送到当前会话，请查看最新一条机器人消息。",
            reply_markup=auto_reply_preview_keyboard(rule.id, target_chat_id),
        )
        return

    preview_lines = [
        "👁️ 自动回复预览",
        "",
        "以下为命中后机器人的回复效果预览：",
        "",
        rule.reply_content,
    ]
    await q.edit_message_text(
        "\n".join(preview_lines),
        reply_markup=auto_reply_preview_keyboard(rule.id, target_chat_id),
    )
