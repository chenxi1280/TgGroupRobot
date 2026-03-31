from __future__ import annotations

import copy

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.keyboards.admin.antispam import anti_spam_config_keyboard
from bot.models.core import ChatSettings, ConversationState
from bot.models.enums import ConversationStateType
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.permission_service import PermissionPolicyService
from bot.services.core.chat_service import get_chat_settings
from bot.services.moderation.anti_spam_service import DEFAULT_RULES, get_antispam_rules
from bot.services.state.conversation_state_service import ConversationStateService
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely, mark_callback_query_answered


log = structlog.get_logger(__name__)

RULE_CODE_MAP = {
    "ait": "ai_text",
    "gad": "global_ads",
    "fld": "flood_attack",
    "ban": "banned_accounts",
    "aig": "ai_image_ads",
    "lnk": "block_links",
    "als": "block_channel_alias",
    "fwd": "block_forwards",
    "men": "block_mentions",
    "eth": "block_eth_address",
    "cmd": "clear_commands",
    "lng": "block_long_content",
}

SPAM_ACTIONS = ["delete", "mute", "ban"]
SPAM_MUTE_VALUES = [300, 600, 1800, 3600, 7200]
SPAM_NOTIFY_SEC_VALUES = [60, 300, 600, 1800]
SPAM_REPEAT_MESSAGES_VALUES = [2, 3, 5, 8]
SPAM_REPEAT_SECONDS_VALUES = [5, 10, 15, 30]

_BOOL_TRUE = {"开启", "开", "on", "true", "1", "yes", "是"}
_BOOL_TRUE_NORMALIZED = {x.lower() for x in _BOOL_TRUE}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in _BOOL_TRUE_NORMALIZED


def _parse_int(value: str, min_value: int) -> int | None:
    try:
        return max(min_value, int(value.strip()))
    except (TypeError, ValueError):
        return None


def _cycle(current: int | str, options: list[int | str]) -> int | str:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_int_list(value: str) -> list[int]:
    values: list[int] = []
    for item in _split_list(value):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def _resolve_target_chat_id(state: ConversationState) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    return None


def format_anti_spam_menu_text(chat_title: str, settings: ChatSettings) -> str:
    rules = get_antispam_rules(settings)
    status = "开启" if settings.anti_spam_enabled else "关闭"
    notify = "开启" if settings.anti_spam_delete_notify else "关闭"
    admin_exempt = "开启" if settings.anti_spam_exempt_admin else "关闭"
    enabled_rule_count = sum(1 for value in rules.values() if isinstance(value, bool) and value)

    def s(key: str) -> str:
        return "开启" if bool(rules.get(key)) else "关闭"

    text = f"🚫 [{chat_title}] 反垃圾（基础版）\n\n"
    text += "当前为集中配置页，尚未拆分为文档中的 11 个独立子入口。\n\n"
    text += f"总开关: {status}\n"
    text += f"惩罚动作: {settings.anti_spam_action}\n"
    text += f"禁言时长: {settings.anti_spam_mute_duration} 秒\n"
    text += f"管理员豁免: {admin_exempt}\n"
    text += f"删除提醒: {notify} ({settings.anti_spam_delete_notify_seconds} 秒)\n"
    text += f"反洪水阈值: {settings.anti_spam_repeat_seconds} 秒内 {settings.anti_spam_repeat_messages} 条\n\n"
    text += f"已启用规则: {enabled_rule_count} 项\n\n"

    text += "AI 屏蔽垃圾消息: " + s("ai_text") + "\n"
    text += "全网拦截广告: " + s("global_ads") + "\n"
    text += "反洪水攻击: " + s("flood_attack") + "\n"
    text += "屏蔽被封禁账号: " + s("banned_accounts") + "\n"
    text += "AI 屏蔽图片广告: " + s("ai_image_ads") + "\n"
    text += "屏蔽链接: " + s("block_links") + "\n"
    text += "屏蔽频道马甲发言: " + s("block_channel_alias") + "\n"
    text += "屏蔽来自频道/用户转发: " + s("block_forwards") + "\n"
    text += "屏蔽 @群组/@用户 ID: " + s("block_mentions") + "\n"
    text += "屏蔽以太坊地址: " + s("block_eth_address") + "\n"
    text += "清除命令消息: " + s("clear_commands") + "\n"
    text += "屏蔽超长消息/姓名: " + s("block_long_content") + "\n"
    text += f"超长阈值: 消息{rules['message_max_length']} 字, 姓名{rules['name_max_length']} 字\n"
    text += f"例外用户: {len(rules['exception_user_ids'])} 个, 例外群组: {len(rules['exception_chat_ids'])} 个"
    return text


async def anti_spam_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query

    if update.effective_chat is None or update.effective_chat.type != "private":
        await answer_callback_query_safely(update, "请在私聊配置反垃圾", show_alert=True)
        return

    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 4:
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
        rules = get_antispam_rules(settings)

        if op == "toggle":
            if key == "enabled":
                settings.anti_spam_enabled = not bool(settings.anti_spam_enabled)
            elif key == "admin_exempt":
                settings.anti_spam_exempt_admin = not bool(settings.anti_spam_exempt_admin)
            elif key == "notify":
                settings.anti_spam_delete_notify = not bool(settings.anti_spam_delete_notify)

        elif op == "cycle":
            if key == "action":
                settings.anti_spam_action = str(_cycle(settings.anti_spam_action, SPAM_ACTIONS))
            elif key == "mute":
                settings.anti_spam_mute_duration = int(_cycle(settings.anti_spam_mute_duration, SPAM_MUTE_VALUES))
            elif key == "notify_sec":
                settings.anti_spam_delete_notify_seconds = int(
                    _cycle(settings.anti_spam_delete_notify_seconds, SPAM_NOTIFY_SEC_VALUES)
                )
            elif key == "repeat_msgs":
                settings.anti_spam_repeat_messages = int(
                    _cycle(settings.anti_spam_repeat_messages, SPAM_REPEAT_MESSAGES_VALUES)
                )
            elif key == "repeat_sec":
                settings.anti_spam_repeat_seconds = int(
                    _cycle(settings.anti_spam_repeat_seconds, SPAM_REPEAT_SECONDS_VALUES)
                )

        elif op == "rule":
            rule_key = RULE_CODE_MAP.get(key)
            if rule_key:
                rules[rule_key] = not bool(rules.get(rule_key))
                settings.anti_spam_rules = rules

        await session.commit()
        settings = await get_chat_settings(session, chat_id)

    from bot.handlers.admin_handler import AdminHandler

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

    text = (
        "🚫 反垃圾文本配置 ( /cancel 取消 )\n\n"
        "支持按键值配置，示例：\n\n"
        "状态: 开启\n"
        "惩罚动作: mute\n"
        "禁言时长: 3600\n"
        "管理员豁免: 开启\n"
        "删除提醒: 开启\n"
        "删除提醒时长: 600\n"
        "反洪水条数: 3\n"
        "反洪水间隔: 15\n"
        "AI屏蔽垃圾消息: 开启\n"
        "全网拦截广告: 开启\n"
        "反洪水攻击: 开启\n"
        "屏蔽被封禁账号: 开启\n"
        "AI屏蔽图片广告: 开启\n"
        "屏蔽链接: 开启\n"
        "屏蔽频道马甲发言: 开启\n"
        "屏蔽来自频道/用户转发: 开启\n"
        "屏蔽@群组ID/@用户ID: 开启\n"
        "屏蔽以太坊地址: 开启\n"
        "清除命令消息: 开启\n"
        "屏蔽超长消息/姓名: 开启\n"
        "消息最大长度: 500\n"
        "姓名最大长度: 32\n"
        "例外用户ID: 12345,67890\n"
        "例外群组ID: -100111,-100222\n"
        "封禁账号名单: 111,222\n"
        "屏蔽转发来源频道ID: -100333\n"
        "屏蔽转发来源用户ID: 999\n"
        "屏蔽@对象ID: 555\n"
        "链接黑名单: scam.com,bad.site"
    )
    await q.edit_message_text(text)


async def anti_spam_config_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: ConversationState,
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
    rules = get_antispam_rules(settings)

    key_mapping = {
        "AI屏蔽垃圾消息": "ai_text",
        "全网拦截广告": "global_ads",
        "反洪水攻击": "flood_attack",
        "屏蔽被封禁账号": "banned_accounts",
        "AI屏蔽图片广告": "ai_image_ads",
        "屏蔽链接": "block_links",
        "屏蔽频道马甲发言": "block_channel_alias",
        "屏蔽来自频道/用户转发": "block_forwards",
        "屏蔽@群组ID/@用户ID": "block_mentions",
        "屏蔽以太坊地址": "block_eth_address",
        "清除命令消息": "clear_commands",
        "屏蔽超长消息/姓名": "block_long_content",
    }

    lines = [line.strip() for line in message_text.split("\n") if line.strip()]
    invalid_keys: list[str] = []
    for line in lines:
        if ":" not in line:
            continue
        key, value = [x.strip() for x in line.split(":", 1)]

        if key in {"状态", "总开关", "功能总开关"}:
            settings.anti_spam_enabled = _parse_bool(value)
        elif key in {"惩罚动作", "处罚"} and value in {"delete", "mute", "ban"}:
            settings.anti_spam_action = value
        elif key in {"禁言时长", "惩罚禁言"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_spam_mute_duration = parsed
        elif key in {"管理员豁免"}:
            settings.anti_spam_exempt_admin = _parse_bool(value)
        elif key in {"删除提醒", "惩罚删除提醒"}:
            parsed = _parse_int(value, 1)
            if parsed is not None:
                settings.anti_spam_delete_notify = True
                settings.anti_spam_delete_notify_seconds = parsed
            else:
                settings.anti_spam_delete_notify = _parse_bool(value)
        elif key in {"删除提醒时长", "提醒时长"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_spam_delete_notify_seconds = parsed
        elif key in {"反洪水条数", "重复阈值"}:
            parsed = _parse_int(value, 2)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_spam_repeat_messages = parsed
        elif key in {"反洪水间隔", "检测间隔", "检测窗口"}:
            parsed = _parse_int(value, 1)
            if parsed is None:
                invalid_keys.append(key)
                continue
            settings.anti_spam_repeat_seconds = parsed
        elif key in {"消息最大长度"}:
            parsed = _parse_int(value, 20)
            if parsed is None:
                invalid_keys.append(key)
                continue
            rules["message_max_length"] = parsed
        elif key in {"姓名最大长度"}:
            parsed = _parse_int(value, 2)
            if parsed is None:
                invalid_keys.append(key)
                continue
            rules["name_max_length"] = parsed
        elif key in {"例外用户ID", "例外名单-用户"}:
            rules["exception_user_ids"] = _split_int_list(value)
        elif key in {"例外群组ID", "例外名单-群组"}:
            rules["exception_chat_ids"] = _split_int_list(value)
        elif key in {"封禁账号名单", "被封禁账号名单"}:
            rules["banned_user_ids"] = _split_int_list(value)
        elif key in {"屏蔽转发来源频道ID"}:
            rules["blocked_forward_chat_ids"] = _split_int_list(value)
        elif key in {"屏蔽转发来源用户ID"}:
            rules["blocked_forward_user_ids"] = _split_int_list(value)
        elif key in {"屏蔽@对象ID"}:
            rules["blocked_mention_ids"] = _split_int_list(value)
        elif key in {"链接黑名单"}:
            rules["link_blacklist"] = _split_list(value)
        elif key in key_mapping:
            rules[key_mapping[key]] = _parse_bool(value)

    # 清理未知字段，避免历史脏数据扩大
    cleaned_rules = copy.deepcopy(DEFAULT_RULES)
    cleaned_rules.update({k: v for k, v in rules.items() if k in cleaned_rules})
    settings.anti_spam_rules = cleaned_rules

    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()

    db: Database = context.application.bot_data["db"]
    from bot.handlers.admin_handler import AdminHandler

    handler = AdminHandler()
    chat_title = await handler._get_chat_title(db, target_chat_id)
    text = "✅ 反垃圾配置已更新\n\n" + format_anti_spam_menu_text(chat_title, settings)
    if invalid_keys:
        keys = "、".join(sorted(set(invalid_keys)))
        text = f"⚠️ 以下字段值无效，已忽略: {keys}\n\n{text}"
    keyboard = anti_spam_config_keyboard(settings, target_chat_id)
    await update.effective_message.reply_text(text, reply_markup=keyboard)
