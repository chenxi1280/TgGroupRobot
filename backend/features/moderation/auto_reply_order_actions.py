from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def auto_reply_move_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    move_rule_func,
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
        await q.answer("移动失败", show_alert=True)
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("移动失败", show_alert=True)
        return
    direction = parts[4]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        moved = await move_rule_func(
            session,
            chat_id=target_chat_id,
            rule_id=rule_id,
            direction=direction,
        )
        await session.commit()

    if not moved:
        await q.answer("已经不能再移动了", show_alert=True)
        return

    await q.answer("顺序已更新")
    await render_list_func(update, context, target_chat_id=target_chat_id, page=0)
