from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType
_AUTO_REPLY_EDIT_ACTION_THRESHOLD_5 = 5
_AUTO_REPLY_RULE_CONFIG_ACTION_THRESHOLD_5 = 5



async def auto_reply_edit_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    get_rule_in_chat_func,
    set_user_state_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < _AUTO_REPLY_EDIT_ACTION_THRESHOLD_5:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return

    field = parts[4]
    state_map = {
        "keywords": ConversationStateType.auto_reply_edit_keywords.value,
        "content": ConversationStateType.auto_reply_edit_content.value,
        "cover": ConversationStateType.auto_reply_edit_cover.value,
        "buttons": ConversationStateType.auto_reply_edit_buttons.value,
    }
    state_type = state_map.get(field)
    if state_type is None:
        await q.answer("暂不支持该编辑项", show_alert=True)
        return

    prompt_map = {
        "keywords": "💬 自动回复 | 编辑关键词\n\n请输入新的关键词列表，使用英文逗号分隔。\n例如：你好,hi,hello",
        "content": "💬 自动回复 | 编辑回复内容\n\n请输入新的回复内容。",
        "cover": "💬 自动回复 | 编辑封面\n\n请发送图片或视频，发送“清空”可移除封面。",
        "buttons": "💬 自动回复 | 编辑按钮\n\n请输入 JSON 按钮数组，或按“按钮文案|URL”逐行输入。\n发送“清空”可移除按钮。",
    }

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_rule_in_chat_func(session, target_chat_id, rule_id)
        if rule is None:
            await session.commit()
            await q.answer("规则不存在", show_alert=True)
            return
        await set_user_state_func(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id, "rule_id": rule_id},
        )
        await session.commit()

    await q.edit_message_text(
        prompt_map[field],
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]
        ),
    )
    await q.answer()


async def auto_reply_rule_config_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_callback_update_func,
    resolve_target_chat_id_func,
    get_rule_in_chat_func,
    update_rule_func,
    show_rule_detail_func,
) -> None:
    if not ensure_callback_update_func(update):
        return
    q = update.callback_query

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < _AUTO_REPLY_RULE_CONFIG_ACTION_THRESHOLD_5:
        await q.answer("规则不存在", show_alert=True)
        return
    action = parts[1]
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("规则不存在", show_alert=True)
        return
    field = parts[4]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_rule_in_chat_func(session, target_chat_id, rule_id)
        if rule is None or rule.chat_id != target_chat_id:
            await session.commit()
            await q.answer("规则不存在", show_alert=True)
            return

        updated = await _apply_rule_config_update(
            session,
            rule,
            action=action,
            field=field,
            rule_id=rule_id,
            target_chat_id=target_chat_id,
            update_rule_func=update_rule_func,
        )
        if not updated:
            await session.commit()
            await q.answer("无效配置项", show_alert=True)
            return
        await session.commit()

    await show_rule_detail_func(update, context, chat_id=target_chat_id, rule_id=rule_id)
    await q.answer()


async def _apply_rule_config_update(
    session,
    rule,
    *,
    action: str,
    field: str,
    rule_id: int,
    target_chat_id: int,
    update_rule_func,
) -> bool:
    if action == "togglecfg":
        if field == "case":
            await update_rule_func(session, rule_id, chat_id=target_chat_id, case_sensitive=not bool(rule.case_sensitive))
            return True
        if field == "source":
            await update_rule_func(session, rule_id, chat_id=target_chat_id, delete_source=not bool(rule.delete_source))
            return True
        if field == "stop":
            await update_rule_func(
                session,
                rule_id,
                chat_id=target_chat_id,
                stop_after_match=not bool(getattr(rule, "stop_after_match", True)),
            )
            return True
        return False

    if action != "cycle":
        return False

    if field == "match":
        ordered = [
            AutoReplyMatchType.exact.value,
            AutoReplyMatchType.contains.value,
            AutoReplyMatchType.starts_with.value,
            AutoReplyMatchType.ends_with.value,
            AutoReplyMatchType.regex.value,
        ]
        current = getattr(rule, "match_type", AutoReplyMatchType.contains.value)
        next_index = (ordered.index(current) + 1) % len(ordered) if current in ordered else 0
        await update_rule_func(session, rule_id, chat_id=target_chat_id, match_type=ordered[next_index])
        return True

    if field == "delay":
        values = [0, 30, 60, 300, 600]
        current_delay = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0)
        next_index = (values.index(current_delay) + 1) % len(values) if current_delay in values else 0
        await update_rule_func(
            session,
            rule_id,
            chat_id=target_chat_id,
            delete_reply_delay_seconds=values[next_index],
        )
        return True

    return False
