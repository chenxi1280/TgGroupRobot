from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.admin.ui.antispam import anti_flood_config_keyboard
from backend.platform.db.schema.models.core import ChatSettings, ConversationState
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.services.chat_service import get_chat_settings
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered

_ANTI_FLOOD_CALLBACK_PARTS = 4
_MIN_MESSAGE_COUNT = 2
_MIN_POSITIVE_VALUE = 1



log = structlog.get_logger(__name__)


FLOOD_ACTIONS = ["delete", "mute", "ban"]
FLOOD_MESSAGES_VALUES = [3, 5, 7, 10]
FLOOD_SECONDS_VALUES = [3, 5, 10, 15]
FLOOD_MUTE_VALUES = [300, 600, 1800, 3600]
FLOOD_NOTIFY_SECONDS_VALUES = [60, 300, 600, 1800]


_BOOL_TRUE = {"开启", "开", "on", "true", "1", "yes", "是"}
_BOOL_TRUE_NORMALIZED = {x.lower() for x in _BOOL_TRUE}
_TOGGLE_FIELDS = {
    "enabled": "anti_flood_enabled",
    "admin_exempt": "anti_flood_exempt_admin",
    "cleanup": "anti_flood_cleanup_messages",
    "notify": "anti_flood_delete_notify",
}
_CYCLE_FIELDS = {
    "messages": ("anti_flood_messages", FLOOD_MESSAGES_VALUES, int),
    "seconds": ("anti_flood_seconds", FLOOD_SECONDS_VALUES, int),
    "action": ("anti_flood_action", FLOOD_ACTIONS, str),
    "mute": ("anti_flood_mute_duration", FLOOD_MUTE_VALUES, int),
    "notify_sec": ("anti_flood_delete_notify_seconds", FLOOD_NOTIFY_SECONDS_VALUES, int),
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in _BOOL_TRUE_NORMALIZED


def _parse_int(value: str, min_value: int) -> int | None:
    try:
        return max(min_value, int(value.strip()))
    except (TypeError, ValueError):
        return None


def format_anti_flood_menu_text(chat_title: str, settings: ChatSettings) -> str:
    status = "开启" if settings.anti_flood_enabled else "关闭"
    cleanup = "开启" if settings.anti_flood_cleanup_messages else "关闭"
    notify = "开启" if settings.anti_flood_delete_notify else "关闭"
    admin_exempt = "开启" if settings.anti_flood_exempt_admin else "关闭"
    return (
        f"🌊 [{chat_title}] 防刷屏\n\n"
        f"状态: {status}\n"
        f"触发条件: {settings.anti_flood_seconds} 秒内发送 {settings.anti_flood_messages} 条消息\n"
        f"惩罚动作: {settings.anti_flood_action}\n"
        f"禁言时长: {settings.anti_flood_mute_duration} 秒\n"
        f"管理员豁免: {admin_exempt}\n"
        f"触发后清理消息: {cleanup}\n"
        f"删除提醒: {notify}\n"
        f"删除提醒时长: {settings.anti_flood_delete_notify_seconds} 秒\n\n"
        f"💡 可用按钮快速切换，也可点“文本配置”一次性设置"
    )


def _cycle(current: int | str, options: list[int | str]) -> int | str:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _resolve_target_chat_id(state: ConversationState) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    return None


def _valid_callback_operation(op: str, key: str) -> bool:
    if op == "toggle":
        return key in _TOGGLE_FIELDS
    if op == "cycle":
        return key in _CYCLE_FIELDS
    return False


async def _callback_command(update: Update) -> tuple[str, str, int] | None:
    if update.effective_chat is None or update.effective_chat.type != "private":
        await answer_callback_query_safely(update, "请在私聊配置防刷屏", show_alert=True)
        return None
    callback = CallbackParser.parse(update.callback_query.data or "")
    if callback.length() < _ANTI_FLOOD_CALLBACK_PARTS:
        await answer_callback_query_safely(update, "防刷屏配置指令不完整", show_alert=True)
        return None
    op, key = callback.get(1), callback.get(2)
    chat_id = callback.get_int_optional(3)
    if chat_id is None or chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组 ID", show_alert=True)
        return None
    if not _valid_callback_operation(op, key):
        await answer_callback_query_safely(update, "不支持的防刷屏配置操作", show_alert=True)
        return None
    return op, key, chat_id


async def _can_manage_flood_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=chat_id,
        user_id=update.effective_user.id,
        capability="settings",
    )
    if allowed:
        return True
    await answer_callback_query_safely(update, reason or "你没有该群组的管理权限", show_alert=True)
    return False


def _apply_callback_operation(settings: ChatSettings, op: str, key: str) -> None:
    if op == "toggle":
        field = _TOGGLE_FIELDS[key]
        setattr(settings, field, not bool(getattr(settings, field)))
        return
    field, options, converter = _CYCLE_FIELDS[key]
    setattr(settings, field, converter(_cycle(getattr(settings, field), options)))


async def _update_flood_setting(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, user_id: int, op: str, key: str):
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=user_id,
        )
        settings = await get_chat_settings(session, chat_id)
        _apply_callback_operation(settings, op, key)
        await session.commit()
        return await get_chat_settings(session, chat_id)


async def _render_flood_menu(query, context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, settings) -> None:
    from backend.features.admin.admin_handler import AdminHandler

    db: Database = context.application.bot_data["db"]
    chat_title = await AdminHandler()._get_chat_title(db, chat_id)
    text = format_anti_flood_menu_text(chat_title, settings)
    await query.edit_message_text(text, reply_markup=anti_flood_config_keyboard(settings, chat_id))


async def anti_flood_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    command = await _callback_command(update)
    if command is None:
        return
    op, key, chat_id = command
    if not await _can_manage_flood_settings(update, context, chat_id):
        return
    query = update.callback_query
    await query.answer()
    mark_callback_query_answered(update)
    settings = await _update_flood_setting(
        context,
        chat_id=chat_id,
        user_id=update.effective_user.id,
        op=op,
        key=key,
    )
    await _render_flood_menu(query, context, chat_id=chat_id, settings=settings)


async def start_anti_flood_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
) -> None:
    """进入防刷屏文本配置状态"""
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
            state_type=ConversationStateType.anti_flood_config.value,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    text = (
        "🌊 防刷屏文本配置 ( /cancel 取消 )\n\n"
        "请按以下格式发送（只改需要的项）：\n\n"
        "状态: 开启\n"
        "触发条数: 5\n"
        "检测间隔: 5\n"
        "惩罚动作: mute\n"
        "禁言时长: 3600\n"
        "管理员豁免: 开启\n"
        "触发后清理消息: 开启\n"
        "删除提醒: 开启\n"
        "删除提醒时长: 600"
    )
    await q.edit_message_text(text)


def _parse_action(value: str) -> str | None:
    return value if value in FLOOD_ACTIONS else None


def _parse_notify(value: str) -> tuple[bool, int | None]:
    stripped = value.strip()
    if stripped.isdigit():
        return True, max(_MIN_POSITIVE_VALUE, int(stripped))
    return _parse_bool(value), None


_TEXT_CONFIG_FIELDS = {
    "状态": ("anti_flood_enabled", _parse_bool),
    "总开关": ("anti_flood_enabled", _parse_bool),
    "功能总开关": ("anti_flood_enabled", _parse_bool),
    "触发条数": ("anti_flood_messages", lambda value: _parse_int(value, _MIN_MESSAGE_COUNT)),
    "触发消息数": ("anti_flood_messages", lambda value: _parse_int(value, _MIN_MESSAGE_COUNT)),
    "触发条件-消息数": ("anti_flood_messages", lambda value: _parse_int(value, _MIN_MESSAGE_COUNT)),
    "检测间隔": ("anti_flood_seconds", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "时间窗口": ("anti_flood_seconds", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "触发条件-秒数": ("anti_flood_seconds", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "惩罚动作": ("anti_flood_action", _parse_action),
    "处罚": ("anti_flood_action", _parse_action),
    "禁言时长": ("anti_flood_mute_duration", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "惩罚禁言": ("anti_flood_mute_duration", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "管理员豁免": ("anti_flood_exempt_admin", _parse_bool),
    "触发后清理消息": ("anti_flood_cleanup_messages", _parse_bool),
    "删除提醒时长": ("anti_flood_delete_notify_seconds", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
    "提醒时长": ("anti_flood_delete_notify_seconds", lambda value: _parse_int(value, _MIN_POSITIVE_VALUE)),
}
_NOTIFY_KEYS = frozenset({"删除提醒", "惩罚删除提醒"})


def _apply_text_config_field(settings: ChatSettings, key: str, value: str) -> bool:
    if key in _NOTIFY_KEYS:
        enabled, seconds = _parse_notify(value)
        settings.anti_flood_delete_notify = enabled
        if seconds is not None:
            settings.anti_flood_delete_notify_seconds = seconds
        return True
    rule = _TEXT_CONFIG_FIELDS.get(key)
    if rule is None:
        return False
    field, parser = rule
    parsed = parser(value)
    if parsed is None:
        return False
    setattr(settings, field, parsed)
    return True


def _apply_text_config(settings: ChatSettings, message_text: str) -> list[str]:
    invalid_keys: list[str] = []
    for raw_line in (line.strip() for line in message_text.splitlines() if line.strip()):
        if ":" not in raw_line:
            invalid_keys.append(raw_line)
            continue
        key, value = (part.strip() for part in raw_line.split(":", 1))
        if not _apply_text_config_field(settings, key, value):
            invalid_keys.append(key)
    return invalid_keys


async def _resolve_message_target(update: Update, session, state: ConversationState) -> int | None:
    target_chat_id = _resolve_target_chat_id(state)
    if target_chat_id is not None:
        return target_chat_id
    await ConversationStateService.clear(session, state.chat_id, update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("❌ 无效的群组 ID，请重新进入配置")
    return None


async def _require_message_permission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    *,
    target_chat_id: int,
) -> bool:
    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=target_chat_id,
        user_id=update.effective_user.id,
        capability="settings",
    )
    if allowed:
        return True
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(f"❌ {reason or '需要管理员权限'}")
    return False


async def _reply_config_result(update: Update, context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, settings, invalid_keys) -> None:
    from backend.features.admin.admin_handler import AdminHandler

    db: Database = context.application.bot_data["db"]
    chat_title = await AdminHandler()._get_chat_title(db, chat_id)
    text = "✅ 防刷屏配置已更新\n\n" + format_anti_flood_menu_text(chat_title, settings)
    if invalid_keys:
        keys = "、".join(sorted(set(invalid_keys)))
        text = f"⚠️ 以下字段值无效，已忽略: {keys}\n\n{text}"
    keyboard = anti_flood_config_keyboard(settings, chat_id)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def anti_flood_config_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    *, state: ConversationState,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = await _resolve_message_target(update, session, state)
    if target_chat_id is None:
        return
    if not await _require_message_permission(update, context, session, target_chat_id=target_chat_id):
        return
    await ModuleSettingsService.ensure(
        session,
        chat_id=target_chat_id,
        chat_type="supergroup" if target_chat_id < 0 else "private",
        user_id=update.effective_user.id,
    )
    settings = await get_chat_settings(session, target_chat_id)
    invalid_keys = _apply_text_config(settings, message_text)
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()
    await _reply_config_result(
        update,
        context,
        chat_id=target_chat_id,
        settings=settings,
        invalid_keys=invalid_keys,
    )
