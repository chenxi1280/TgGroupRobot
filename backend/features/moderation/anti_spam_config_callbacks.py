from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.ui.antispam import anti_spam_config_keyboard
from backend.features.moderation.anti_spam_config_presenter import anti_spam_config_prompt_text, format_anti_spam_menu_text
from backend.features.moderation.anti_spam_config_utils import (
    RULE_CODE_MAP,
    SPAM_ACTIONS,
    SPAM_MUTE_VALUES,
    SPAM_NOTIFY_SEC_VALUES,
    SPAM_REPEAT_MESSAGES_VALUES,
    SPAM_REPEAT_SECONDS_VALUES,
    _cycle,
)
from backend.features.moderation.services.anti_spam_service import get_antispam_rules
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
_ANTI_SPAM_CONFIG_CALLBACK_THRESHOLD_4 = 4


def _toggle_anti_spam_setting(settings, key: str) -> bool:
    fields = {
        "enabled": "anti_spam_enabled",
        "admin_exempt": "anti_spam_exempt_admin",
        "notify": "anti_spam_delete_notify",
    }
    field = fields.get(key)
    if field is None:
        return False
    setattr(settings, field, not bool(getattr(settings, field)))
    return True


def _cycle_anti_spam_setting(settings, key: str) -> bool:
    fields = {
        "action": ("anti_spam_action", SPAM_ACTIONS, str),
        "mute": ("anti_spam_mute_duration", SPAM_MUTE_VALUES, int),
        "notify_sec": ("anti_spam_delete_notify_seconds", SPAM_NOTIFY_SEC_VALUES, int),
        "repeat_msgs": ("anti_spam_repeat_messages", SPAM_REPEAT_MESSAGES_VALUES, int),
        "repeat_sec": ("anti_spam_repeat_seconds", SPAM_REPEAT_SECONDS_VALUES, int),
    }
    config = fields.get(key)
    if config is None:
        return False
    field, values, convert = config
    setattr(settings, field, convert(_cycle(getattr(settings, field), values)))
    return True


def _toggle_anti_spam_rule(settings, rules: dict, key: str) -> bool:
    rule_key = RULE_CODE_MAP.get(key)
    if rule_key is None:
        return False
    updated_rules = {**rules, rule_key: not bool(rules.get(rule_key))}
    settings.anti_spam_rules = updated_rules
    return True


def _apply_anti_spam_operation(settings, rules: dict, *, op: str, key: str) -> bool:
    if op == "toggle":
        return _toggle_anti_spam_setting(settings, key)
    if op == "cycle":
        return _cycle_anti_spam_setting(settings, key)
    if op == "rule":
        return _toggle_anti_spam_rule(settings, rules, key)
    return False


async def _resolve_anti_spam_request(update, context, *, cb):
    chat_id = cb.get_int_optional(3)
    if chat_id is None or chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组 ID", show_alert=True)
        return None
    allowed, reason = await PermissionPolicyService.require_manage(
        context, chat_id=chat_id, user_id=update.effective_user.id,
        capability="settings",
    )
    if allowed:
        return chat_id
    await answer_callback_query_safely(
        update, reason or "你没有该群组的管理权限", show_alert=True
    )
    return None


async def anti_spam_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query

    if update.effective_chat is None or update.effective_chat.type != "private":
        await answer_callback_query_safely(update, "请在私聊配置反垃圾", show_alert=True)
        return

    cb = CallbackParser.parse(q.data or "")
    if cb.length() < _ANTI_SPAM_CONFIG_CALLBACK_THRESHOLD_4:
        return

    chat_id = await _resolve_anti_spam_request(update, context, cb=cb)
    if chat_id is None:
        return

    await q.answer()
    mark_callback_query_answered(update)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        settings = await get_chat_settings(session, chat_id)
        rules = get_antispam_rules(settings)

        applied = _apply_anti_spam_operation(
            settings, rules, op=cb.get(1), key=cb.get(2)
        )
        if not applied:
            await answer_callback_query_safely(
                update, "无效的反垃圾配置操作", show_alert=True
            )
            return
        await session.commit()
        settings = await get_chat_settings(session, chat_id)

    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    chat_title = await handler._get_chat_title(db, chat_id)
    text = format_anti_spam_menu_text(chat_title, settings)
    keyboard = anti_spam_config_keyboard(settings, chat_id)
    await q.edit_message_text(text, reply_markup=keyboard)


async def start_anti_spam_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
) -> None:
    """进入反垃圾文本配置状态"""
    if update.effective_user is None or update.callback_query is None:
        return

    q = update.callback_query
    if target_chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组 ID", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=target_chat_id,
            chat_type="supergroup" if target_chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
        await ConversationStateService.start(
            session,
            chat_id=target_chat_id,
            user_id=update.effective_user.id,
            state_type=ConversationStateType.anti_spam_config.value,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    await q.edit_message_text(anti_spam_config_prompt_text())
