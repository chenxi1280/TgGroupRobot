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
_ANTI_FLOOD_CONFIG_CALLBACK_THRESHOLD_4 = 4



log = structlog.get_logger(__name__)


FLOOD_ACTIONS = ["delete", "mute", "ban"]
FLOOD_MESSAGES_VALUES = [3, 5, 7, 10]
FLOOD_SECONDS_VALUES = [3, 5, 10, 15]
FLOOD_MUTE_VALUES = [300, 600, 1800, 3600]
FLOOD_NOTIFY_SECONDS_VALUES = [60, 300, 600, 1800]


_BOOL_TRUE = {"开启", "开", "on", "true", "1", "yes", "是"}
_BOOL_TRUE_NORMALIZED = {x.lower() for x in _BOOL_TRUE}


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


async def anti_flood_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query

    if update.effective_chat is None or update.effective_chat.type != "private":
        await answer_callback_query_safely(update, "请在私聊配置防刷屏", show_alert=True)
        return

    cb = CallbackParser.parse(q.data or "")
    if cb.length() < _ANTI_FLOOD_CONFIG_CALLBACK_THRESHOLD_4:
        return

    op = cb.get(1)
    key = cb.get(2)
    chat_id = cb.get_int_optional(3)
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

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        settings = await get_chat_settings(session, chat_id)

        if op == "toggle":
            mapping = {
                "enabled": "anti_flood_enabled",
                "admin_exempt": "anti_flood_exempt_admin",
                "cleanup": "anti_flood_cleanup_messages",
                "notify": "anti_flood_delete_notify",
            }
            field = mapping.get(key)
            if field:
                setattr(settings, field, not bool(getattr(settings, field)))

        elif op == "cycle":
            if key == "messages":
                settings.anti_flood_messages = int(_cycle(settings.anti_flood_messages, FLOOD_MESSAGES_VALUES))
            elif key == "seconds":
                settings.anti_flood_seconds = int(_cycle(settings.anti_flood_seconds, FLOOD_SECONDS_VALUES))
            elif key == "action":
                settings.anti_flood_action = str(_cycle(settings.anti_flood_action, FLOOD_ACTIONS))
            elif key == "mute":
                settings.anti_flood_mute_duration = int(_cycle(settings.anti_flood_mute_duration, FLOOD_MUTE_VALUES))
            elif key == "notify_sec":
                settings.anti_flood_delete_notify_seconds = int(
                    _cycle(settings.anti_flood_delete_notify_seconds, FLOOD_NOTIFY_SECONDS_VALUES)
                )

        await session.commit()

        # 重新获取，确保显示最新值
        settings = await get_chat_settings(session, chat_id)

    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    chat_title = await handler._get_chat_title(db, chat_id)
    text = format_anti_flood_menu_text(chat_title, settings)
    keyboard = anti_flood_config_keyboard(settings, chat_id)
    await q.edit_message_text(text, reply_markup=keyboard)


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


async def anti_flood_config_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    *, state: ConversationState,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = _resolve_target_chat_id(state)
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

    await ModuleSettingsService.ensure(
        session,
        chat_id=target_chat_id,
        chat_type="supergroup" if target_chat_id < 0 else "private",
        user_id=update.effective_user.id,
    )
    settings = await get_chat_settings(session, target_chat_id)

    lines = [line.strip() for line in message_text.split("\n") if line.strip()]
    invalid_keys: list[str] = []
    for line in lines:
        if ":" not in line:
            continue
        key, value = [x.strip() for x in line.split(":", 1)]

        if key in {"状态", "总开关", "功能总开关"}:
            settings.anti_flood_enabled = _parse_bool(value)
        elif key in {"触发条数", "触发消息数", "触发条件-消息数"}:
            parsed = _parse_int(value, 2)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_flood_messages = parsed
        elif key in {"检测间隔", "时间窗口", "触发条件-秒数"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_flood_seconds = parsed
        elif key in {"惩罚动作", "处罚"} and value in {"delete", "mute", "ban"}:
            settings.anti_flood_action = value
        elif key in {"禁言时长", "惩罚禁言"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_flood_mute_duration = parsed
        elif key in {"管理员豁免"}:
            settings.anti_flood_exempt_admin = _parse_bool(value)
        elif key in {"触发后清理消息"}:
            settings.anti_flood_cleanup_messages = _parse_bool(value)
        elif key in {"删除提醒", "惩罚删除提醒"}:
            if value.strip().isdigit():
                settings.anti_flood_delete_notify = True
                settings.anti_flood_delete_notify_seconds = max(1, int(value.strip()))
            else:
                settings.anti_flood_delete_notify = _parse_bool(value)
        elif key in {"删除提醒时长", "提醒时长"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_flood_delete_notify_seconds = parsed

    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()

    db: Database = context.application.bot_data["db"]
    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    chat_title = await handler._get_chat_title(db, target_chat_id)

    text = "✅ 防刷屏配置已更新\n\n" + format_anti_flood_menu_text(chat_title, settings)
    if invalid_keys:
        keys = "、".join(sorted(set(invalid_keys)))
        text = f"⚠️ 以下字段值无效，已忽略: {keys}\n\n{text}"
    keyboard = anti_flood_config_keyboard(settings, target_chat_id)
    await update.effective_message.reply_text(text, reply_markup=keyboard)
