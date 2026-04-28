from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from backend.features.admin.ui.antispam import (
    format_garbage_guard_home_text,
    format_garbage_rule_text,
    format_garbage_whitelist_text,
    garbage_guard_home_keyboard,
    garbage_guard_rule_keyboard,
    garbage_guard_whitelist_keyboard,
)
from backend.features.moderation.services.banned_word_service import get_chat_banned_words
from backend.features.moderation.services.garbage_guard_rules import (
    RULE_CYCLE_VALUES,
    RULE_DEFINITIONS,
    cycle_rule_value,
    get_rule_config,
    set_global_whitelist_user_ids,
    set_rule_config,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ConversationState
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService


_INT_RE = re.compile(r"-?\d+")


async def _edit_config_message(q, text: str, reply_markup=None) -> None:
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _get_chat_title(db: Database, chat_id: int) -> str:
    from backend.features.admin.admin_handler import AdminHandler

    return await AdminHandler()._get_chat_title(db, chat_id)


async def _count_banned_words(session: AsyncSession, chat_id: int) -> int:
    return len(await get_chat_banned_words(session, chat_id))


async def _render_home(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    q = update.callback_query
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.commit()
    chat_title = await _get_chat_title(db, chat_id)
    await _edit_config_message(
        q,
        format_garbage_guard_home_text(chat_title, settings),
        reply_markup=garbage_guard_home_keyboard(settings, chat_id),
    )


async def _render_rule(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, rule_id: str) -> None:
    q = update.callback_query
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        banned_word_count = await _count_banned_words(session, chat_id) if rule_id == "banned_words" else 0
        await session.commit()
    chat_title = await _get_chat_title(db, chat_id)
    await _edit_config_message(
        q,
        format_garbage_rule_text(chat_title, settings, rule_id, banned_word_count=banned_word_count),
        reply_markup=garbage_guard_rule_keyboard(settings, chat_id, rule_id, banned_word_count=banned_word_count),
    )


async def _render_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    q = update.callback_query
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.commit()
    chat_title = await _get_chat_title(db, chat_id)
    await _edit_config_message(
        q,
        format_garbage_whitelist_text(chat_title, settings),
        reply_markup=garbage_guard_whitelist_keyboard(chat_id),
    )


async def garbage_guard_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return

    op = cb.get(1)
    if op == "noop":
        await answer_callback_query_safely(update, "当前项无需配置")
        return

    if op in {"home", "whitelist"}:
        chat_id = cb.get_int_optional(2)
    elif op in {"clear"}:
        chat_id = cb.get_int_optional(3)
    elif op == "input":
        chat_id = cb.get_int_optional(3)
    else:
        chat_id = cb.get_int_optional(4) if cb.length() >= 5 else cb.get_int_optional(3)

    if chat_id is None or chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组 ID", show_alert=True)
        return

    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=chat_id,
        user_id=update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        await answer_callback_query_safely(update, reason or "你没有该群组的管理权限", show_alert=True)
        return

    await q.answer()
    mark_callback_query_answered(update)

    if op == "home":
        await _render_home(update, context, chat_id)
        return

    if op == "whitelist":
        await _render_whitelist(update, context, chat_id)
        return

    db: Database = context.application.bot_data["db"]
    if op == "input" and cb.get(2) == "whitelist":
        async with db.session_factory() as session:
            await ModuleSettingsService.ensure(
                session,
                chat_id=chat_id,
                chat_type="supergroup" if chat_id < 0 else "private",
                user_id=update.effective_user.id,
            )
            await ConversationStateService.clear(session, chat_id, update.effective_user.id)
            await ConversationStateService.start(
                session,
                chat_id=chat_id,
                user_id=update.effective_user.id,
                state_type=ConversationStateType.garbage_guard_whitelist.value,
                state_data={"target_chat_id": chat_id},
            )
            await session.commit()
        await _edit_config_message(
            q,
            "📄 总白名单管理\n\n请输入用户 ID，多个 ID 可用空格、逗号或换行分隔。\n发送“清空”可清空白名单。",
        )
        return

    if op == "clear" and cb.get(2) == "whitelist":
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            set_global_whitelist_user_ids(settings, [])
            await session.commit()
        await _render_whitelist(update, context, chat_id)
        return

    if op == "rule":
        rule_id = cb.get(2)
        if rule_id not in RULE_DEFINITIONS:
            await answer_callback_query_safely(update, "规则不存在", show_alert=True)
            return
        await _render_rule(update, context, chat_id, rule_id)
        return

    if op not in {"toggle", "cycle"}:
        return

    rule_id = cb.get(2)
    field = cb.get(3)
    if rule_id not in RULE_DEFINITIONS:
        await answer_callback_query_safely(update, "规则不存在", show_alert=True)
        return

    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        settings = await get_chat_settings(session, chat_id)
        rule = get_rule_config(settings, rule_id)
        if op == "toggle":
            if field in rule:
                set_rule_config(settings, rule_id, {field: not bool(rule.get(field))})
        elif op == "cycle" and field in RULE_CYCLE_VALUES:
            cycle_rule_value(settings, rule_id, field)
        await session.commit()

    await _render_rule(update, context, chat_id, rule_id)


async def garbage_guard_whitelist_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: ConversationState,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else state.chat_id
    if not isinstance(target_chat_id, int) or target_chat_id == 0:
        await ConversationStateService.clear(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("❌ 无效的群组 ID，请重新进入配置")
        return

    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=target_chat_id,
        user_id=update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(f"❌ {reason or '需要管理员权限'}")
        return

    settings = await get_chat_settings(session, target_chat_id)
    if message_text.strip() in {"清空", "/clear"}:
        user_ids: list[int] = []
    else:
        user_ids = [int(value) for value in _INT_RE.findall(message_text)]
    set_global_whitelist_user_ids(settings, user_ids)
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()

    db: Database = context.application.bot_data["db"]
    chat_title = await _get_chat_title(db, target_chat_id)
    await update.effective_message.reply_text(
        "✅ 总白名单已更新\n\n" + format_garbage_whitelist_text(chat_title, settings),
        reply_markup=garbage_guard_whitelist_keyboard(target_chat_id),
    )
