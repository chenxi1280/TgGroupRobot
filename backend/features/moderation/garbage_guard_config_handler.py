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
from backend.features.moderation.services.quick_reply_actions import parse_quick_reply_keyword_input
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
MIN_CALLBACK_PARTS = 3
FULL_CALLBACK_PARTS = 5
QUICK_REPLY_FIELDS = frozenset({"mute_keyword", "kick_keyword"})


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


async def _render_rule(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, *, rule_id: str) -> None:
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


def _extract_config_chat_id(cb: CallbackParser, op: str) -> int | None:
    if op in {"home", "whitelist"}:
        return cb.get_int_optional(2)
    if op == "clear":
        return cb.get_int_optional(3)
    if op == "input":
        index = 4 if cb.get(2) == "quick_reply_actions" else 3
        return cb.get_int_optional(index)
    index = 4 if cb.length() >= FULL_CALLBACK_PARTS else 3
    return cb.get_int_optional(index)


async def _start_garbage_config_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    state_type: str,
    state_data: dict,
    prompt: str,
) -> None:
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=user_id,
        )
        await ConversationStateService.clear(session, chat_id, user_id)
        await ConversationStateService.start(
            session,
            chat_id=chat_id,
            user_id=user_id,
            state_type=state_type,
            state_data=state_data,
        )
        await session.commit()
    await _edit_config_message(update.callback_query, prompt)


async def _handle_config_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    cb: CallbackParser,
) -> bool:
    input_type = cb.get(2)
    if input_type == "whitelist":
        await _start_garbage_config_input(
            update,
            context,
            chat_id,
            state_type=ConversationStateType.garbage_guard_whitelist.value,
            state_data={"target_chat_id": chat_id},
            prompt=(
                "📄 总白名单管理\n\n请输入用户 ID，多个 ID 可用空格、逗号或换行分隔。\n"
                "发送“清空”可清空白名单。"
            ),
        )
        return True
    if input_type != "quick_reply_actions":
        return False
    field = cb.get(3)
    if field not in QUICK_REPLY_FIELDS:
        await answer_callback_query_safely(update, "无效的快捷回复配置项", show_alert=True)
        return True
    label = "禁言回复词" if field == "mute_keyword" else "踢出回复词"
    await _start_garbage_config_input(
        update,
        context,
        chat_id,
        state_type=ConversationStateType.garbage_guard_quick_reply_keyword.value,
        state_data={"target_chat_id": chat_id, "field": field},
        prompt=f"👮 快捷回复操作\n\n请输入新的{label}，例如：j 或 T。\n不能包含空格或换行。",
    )
    return True


async def _clear_whitelist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        set_global_whitelist_user_ids(settings, [])
        await session.commit()
    await _render_whitelist(update, context, chat_id)


def _update_rule_setting(settings, *, op: str, rule_id: str, field: str) -> bool:
    rule = get_rule_config(settings, rule_id)
    if op == "toggle" and field in rule:
        set_rule_config(settings, rule_id, {field: not bool(rule.get(field))})
        return True
    if op == "cycle" and field in RULE_CYCLE_VALUES:
        cycle_rule_value(settings, rule_id, field)
        return True
    return False


async def _mutate_rule_setting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    cb: CallbackParser,
    op: str,
) -> None:
    rule_id = cb.get(2)
    field = cb.get(3)
    if rule_id not in RULE_DEFINITIONS:
        await answer_callback_query_safely(update, "规则不存在", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        settings = await get_chat_settings(session, chat_id)
        updated = _update_rule_setting(settings, op=op, rule_id=rule_id, field=field)
        if not updated:
            await session.commit()
            await answer_callback_query_safely(update, "无效的规则配置项", show_alert=True)
            return
        await session.commit()
    await _render_rule(update, context, chat_id, rule_id=rule_id)


async def _dispatch_config_operation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    cb: CallbackParser,
    op: str,
) -> None:
    if op == "home":
        await _render_home(update, context, chat_id)
        return
    if op == "whitelist":
        await _render_whitelist(update, context, chat_id)
        return
    if op == "input" and await _handle_config_input(update, context, chat_id, cb=cb):
        return
    if op == "clear" and cb.get(2) == "whitelist":
        await _clear_whitelist(update, context, chat_id)
        return
    if op == "rule" and cb.get(2) in RULE_DEFINITIONS:
        await _render_rule(update, context, chat_id, rule_id=cb.get(2))
        return
    if op in {"toggle", "cycle"}:
        await _mutate_rule_setting(update, context, chat_id, cb=cb, op=op)
        return
    await answer_callback_query_safely(update, "无效的垃圾防护操作", show_alert=True)


async def garbage_guard_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < MIN_CALLBACK_PARTS:
        await answer_callback_query_safely(update, "无效的垃圾防护参数", show_alert=True)
        return

    op = cb.get(1)
    if op == "noop":
        await answer_callback_query_safely(update, "当前项无需配置")
        return

    chat_id = _extract_config_chat_id(cb, op)
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
    await _dispatch_config_operation(update, context, chat_id, cb=cb, op=op)


def _get_state_target_chat_id(state: ConversationState) -> int | None:
    value = (state.state_data or {}).get("target_chat_id", state.chat_id)
    return value if isinstance(value, int) and value != 0 else None


def _parse_whitelist_user_ids(message_text: str) -> list[int]:
    if message_text.strip() in {"清空", "/clear"}:
        return []
    return [int(value) for value in _INT_RE.findall(message_text)]


async def garbage_guard_whitelist_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    *, state: ConversationState,
    message_text: str,
) -> None:
    if state.state_type == ConversationStateType.garbage_guard_quick_reply_keyword.value:
        await garbage_guard_quick_reply_keyword_message_handler(update, context, session, state=state, message_text=message_text)
        return

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = _get_state_target_chat_id(state)
    if target_chat_id is None:
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
    user_ids = _parse_whitelist_user_ids(message_text)
    set_global_whitelist_user_ids(settings, user_ids)
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()

    db: Database = context.application.bot_data["db"]
    chat_title = await _get_chat_title(db, target_chat_id)
    await update.effective_message.reply_text(
        "✅ 总白名单已更新\n\n" + format_garbage_whitelist_text(chat_title, settings),
        reply_markup=garbage_guard_whitelist_keyboard(target_chat_id),
    )


async def garbage_guard_quick_reply_keyword_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    *, state: ConversationState,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else state.chat_id
    field = state.state_data.get("field") if state.state_data else None
    if not isinstance(target_chat_id, int) or not isinstance(field, str):
        await ConversationStateService.clear(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("❌ 无效的快捷回复配置，请重新进入配置")
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
    try:
        parsed = parse_quick_reply_keyword_input(field, message_text)
        _ensure_keyword_not_duplicated(settings, parsed.field, parsed.keyword)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return

    set_rule_config(settings, "quick_reply_actions", {parsed.field: parsed.keyword})
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()

    db: Database = context.application.bot_data["db"]
    chat_title = await _get_chat_title(db, target_chat_id)
    await update.effective_message.reply_text(
        "✅ 快捷回复词已更新\n\n" + format_garbage_rule_text(chat_title, settings, "quick_reply_actions"),
        reply_markup=garbage_guard_rule_keyboard(settings, target_chat_id, "quick_reply_actions"),
    )


def _ensure_keyword_not_duplicated(settings, field: str, keyword: str) -> None:
    rule = get_rule_config(settings, "quick_reply_actions")
    other_field = "kick_keyword" if field == "mute_keyword" else "mute_keyword"
    if keyword.casefold() == str(rule.get(other_field, "")).strip().casefold():
        raise ValueError("禁言回复词和踢出回复词不能相同")
