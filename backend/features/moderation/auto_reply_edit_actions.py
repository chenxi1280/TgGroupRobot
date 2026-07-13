from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType

CALLBACK_PART_COUNT = 5
EDIT_STATE_TYPES = {
    "keywords": ConversationStateType.auto_reply_edit_keywords.value,
    "content": ConversationStateType.auto_reply_edit_content.value,
    "cover": ConversationStateType.auto_reply_edit_cover.value,
    "buttons": ConversationStateType.auto_reply_edit_buttons.value,
}
EDIT_PROMPTS = {
    "keywords": "💬 自动回复 | 编辑关键词\n\n请输入新的关键词列表，使用英文逗号分隔。\n例如：你好,hi,hello",
    "content": "💬 自动回复 | 编辑回复内容\n\n请输入新的回复内容。",
    "cover": "💬 自动回复 | 编辑封面\n\n请发送图片或视频，发送“清空”可移除封面。",
    "buttons": "💬 自动回复 | 编辑按钮\n\n请输入 JSON 按钮数组，或按“按钮文案|URL”逐行输入。\n发送“清空”可移除按钮。",
}
MATCH_TYPE_ORDER = (
    AutoReplyMatchType.exact.value,
    AutoReplyMatchType.contains.value,
    AutoReplyMatchType.starts_with.value,
    AutoReplyMatchType.ends_with.value,
    AutoReplyMatchType.regex.value,
)
REPLY_DELETE_DELAYS = (0, 30, 60, 300, 600)


def _parse_rule_field(data: str) -> tuple[int, str] | None:
    parts = data.split(":")
    if len(parts) < CALLBACK_PART_COUNT:
        return None
    try:
        return int(parts[3]), parts[4]
    except ValueError:
        return None


async def _save_edit_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    *,
    rule_id: int,
    state_type: str,
    get_rule_in_chat_func,
    set_user_state_func,
) -> bool:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_rule_in_chat_func(session, target_chat_id, rule_id)
        if rule is None:
            await session.commit()
            return False
        await set_user_state_func(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id, "rule_id": rule_id},
        )
        await session.commit()
    return True


async def _show_edit_prompt(q, *, field: str, target_chat_id: int, rule_id: int) -> None:
    await q.edit_message_text(
        EDIT_PROMPTS[field],
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]
        ),
    )
    await q.answer()

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

    parsed = _parse_rule_field(q.data or "")
    if parsed is None:
        await q.edit_message_text("规则不存在")
        await q.answer()
        return
    rule_id, field = parsed
    state_type = EDIT_STATE_TYPES.get(field)
    if state_type is None:
        await q.answer("暂不支持该编辑项", show_alert=True)
        return
    saved = await _save_edit_state(
        update,
        context,
        target_chat_id,
        rule_id=rule_id,
        state_type=state_type,
        get_rule_in_chat_func=get_rule_in_chat_func,
        set_user_state_func=set_user_state_func,
    )
    if not saved:
        await q.answer("规则不存在", show_alert=True)
        return
    await _show_edit_prompt(q, field=field, target_chat_id=target_chat_id, rule_id=rule_id)


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
    parsed = _parse_rule_field(q.data or "")
    if parsed is None:
        await q.answer("规则不存在", show_alert=True)
        return
    action = parts[1]
    rule_id, field = parsed

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
        return await _toggle_rule_config(
            session,
            rule,
            field=field,
            rule_id=rule_id,
            target_chat_id=target_chat_id,
            update_rule_func=update_rule_func,
        )
    if action == "cycle":
        return await _cycle_rule_config(
            session,
            rule,
            field=field,
            rule_id=rule_id,
            target_chat_id=target_chat_id,
            update_rule_func=update_rule_func,
        )
    return False


async def _toggle_rule_config(
    session,
    rule,
    *,
    field: str,
    rule_id: int,
    target_chat_id: int,
    update_rule_func,
) -> bool:
    update_by_field = {
        "case": {"case_sensitive": not bool(rule.case_sensitive)},
        "source": {"delete_source": not bool(rule.delete_source)},
        "stop": {"stop_after_match": not bool(getattr(rule, "stop_after_match", True))},
    }
    updates = update_by_field.get(field)
    if updates is None:
        return False
    await update_rule_func(session, rule_id, chat_id=target_chat_id, **updates)
    return True


def _next_cycle_value(current, values: tuple):
    return values[(values.index(current) + 1) % len(values)] if current in values else values[0]


async def _cycle_rule_config(
    session,
    rule,
    *,
    field: str,
    rule_id: int,
    target_chat_id: int,
    update_rule_func,
) -> bool:
    if field == "match":
        current = getattr(rule, "match_type", AutoReplyMatchType.contains.value)
        next_value = _next_cycle_value(current, MATCH_TYPE_ORDER)
        await update_rule_func(session, rule_id, chat_id=target_chat_id, match_type=next_value)
        return True
    if field == "delay":
        current_delay = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0)
        next_value = _next_cycle_value(current_delay, REPLY_DELETE_DELAYS)
        await update_rule_func(
            session,
            rule_id,
            chat_id=target_chat_id,
            delete_reply_delay_seconds=next_value,
        )
        return True
    return False
