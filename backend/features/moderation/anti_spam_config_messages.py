from __future__ import annotations

import copy

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.ui.antispam import anti_spam_config_keyboard
from backend.features.moderation.anti_spam_config_presenter import format_anti_spam_menu_text
from backend.features.moderation.anti_spam_config_utils import _resolve_target_chat_id, _split_list
from backend.features.moderation.services.anti_spam_service import DEFAULT_RULES, get_antispam_rules
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ConversationState
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService

_TRUE_VALUES = frozenset({"开启", "开", "on", "true", "1", "yes", "是"})
_FALSE_VALUES = frozenset({"关闭", "关", "off", "false", "0", "no", "否"})
_ACTION_VALUES = frozenset({"delete", "mute", "ban"})
_BOOL_SETTING_FIELDS = {
    "状态": "anti_spam_enabled", "总开关": "anti_spam_enabled",
    "功能总开关": "anti_spam_enabled", "管理员豁免": "anti_spam_exempt_admin",
}
_INT_SETTING_FIELDS = {
    "禁言时长": ("anti_spam_mute_duration", 1),
    "惩罚禁言": ("anti_spam_mute_duration", 1),
    "删除提醒时长": ("anti_spam_delete_notify_seconds", 1),
    "提醒时长": ("anti_spam_delete_notify_seconds", 1),
    "反洪水条数": ("anti_spam_repeat_messages", 2),
    "重复阈值": ("anti_spam_repeat_messages", 2),
    "反洪水间隔": ("anti_spam_repeat_seconds", 1),
    "检测间隔": ("anti_spam_repeat_seconds", 1),
    "检测窗口": ("anti_spam_repeat_seconds", 1),
}
_INT_RULE_FIELDS = {"消息最大长度": ("message_max_length", 20), "姓名最大长度": ("name_max_length", 2)}
_LIST_RULE_FIELDS = {
    "例外用户ID": ("exception_user_ids", True), "例外名单-用户": ("exception_user_ids", True),
    "例外群组ID": ("exception_chat_ids", True), "例外名单-群组": ("exception_chat_ids", True),
    "封禁账号名单": ("banned_user_ids", True), "被封禁账号名单": ("banned_user_ids", True),
    "屏蔽转发来源频道ID": ("blocked_forward_chat_ids", True),
    "屏蔽转发来源用户ID": ("blocked_forward_user_ids", True),
    "屏蔽@对象ID": ("blocked_mention_ids", True), "链接黑名单": ("link_blacklist", False),
}
_BOOL_RULE_FIELDS = {
    "AI屏蔽垃圾消息": "ai_text", "全网拦截广告": "global_ads",
    "反洪水攻击": "flood_attack", "屏蔽被封禁账号": "banned_accounts",
    "AI屏蔽图片广告": "ai_image_ads", "屏蔽链接": "block_links",
    "屏蔽频道马甲发言": "block_channel_alias", "屏蔽来自频道/用户转发": "block_forwards",
    "屏蔽@群组ID/@用户ID": "block_mentions", "屏蔽以太坊地址": "block_eth_address",
    "清除命令消息": "clear_commands", "屏蔽超长消息/姓名": "block_long_content",
}


def _parse_strict_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _parse_strict_int(value: str, *, minimum: int) -> int | None:
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return None
    return max(minimum, parsed)


def _parse_strict_int_list(value: str) -> list[int] | None:
    items = _split_list(value)
    if not items:
        return []
    try:
        return [int(item) for item in items]
    except ValueError:
        return None


def _parse_config_entry(
    key: str, value: str, rules: dict
) -> tuple[dict, dict, bool]:
    if key in _BOOL_SETTING_FIELDS:
        parsed = _parse_strict_bool(value)
        return ({_BOOL_SETTING_FIELDS[key]: parsed}, rules, parsed is not None)
    if key in {"惩罚动作", "处罚"}:
        return ({"anti_spam_action": value}, rules, value in _ACTION_VALUES)
    if key in _INT_SETTING_FIELDS:
        field, minimum = _INT_SETTING_FIELDS[key]
        parsed = _parse_strict_int(value, minimum=minimum)
        return ({field: parsed}, rules, parsed is not None)
    if key in {"删除提醒", "惩罚删除提醒"}:
        parsed_int = _parse_strict_int(value, minimum=1)
        if parsed_int is not None:
            return ({"anti_spam_delete_notify": True, "anti_spam_delete_notify_seconds": parsed_int}, rules, True)
        parsed_bool = _parse_strict_bool(value)
        return ({"anti_spam_delete_notify": parsed_bool}, rules, parsed_bool is not None)
    if key in _INT_RULE_FIELDS:
        field, minimum = _INT_RULE_FIELDS[key]
        parsed = _parse_strict_int(value, minimum=minimum)
        return ({}, {**rules, field: parsed}, parsed is not None)
    if key in _LIST_RULE_FIELDS:
        field, integers = _LIST_RULE_FIELDS[key]
        parsed = _parse_strict_int_list(value) if integers else _split_list(value)
        return ({}, {**rules, field: parsed}, parsed is not None)
    if key in _BOOL_RULE_FIELDS:
        parsed = _parse_strict_bool(value)
        return ({}, {**rules, _BOOL_RULE_FIELDS[key]: parsed}, parsed is not None)
    return {}, rules, False


def _parse_config_text(message_text: str, rules: dict) -> tuple[dict, dict, list[str]]:
    updates: dict = {}
    current_rules = dict(rules)
    invalid: list[str] = []
    lines = [line.strip() for line in message_text.splitlines() if line.strip()]
    for line in lines:
        if ":" not in line:
            invalid.append(line)
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        entry_updates, next_rules, valid = _parse_config_entry(key, value, current_rules)
        if not valid:
            invalid.append(key)
            continue
        updates = {**updates, **entry_updates}
        current_rules = next_rules
    return updates, current_rules, invalid


async def _resolve_config_target(update, context, session, *, state):
    target_chat_id = _resolve_target_chat_id(state)
    if target_chat_id is None:
        await ConversationStateService.clear(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("❌ 无效的群组 ID，请重新进入配置")
        return None
    allowed, reason = await PermissionPolicyService.require_manage(
        context, chat_id=target_chat_id, user_id=update.effective_user.id,
        capability="settings",
    )
    if allowed:
        return target_chat_id
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(f"❌ {reason or '需要管理员权限'}")
    return None


async def _reply_config_result(update, context, *, target_chat_id: int, settings, invalid: list[str]) -> None:
    db: Database = context.application.bot_data["db"]
    from backend.features.admin.admin_handler import AdminHandler

    chat_title = await AdminHandler()._get_chat_title(db, target_chat_id)
    text = "✅ 反垃圾配置已更新\n\n" + format_anti_spam_menu_text(chat_title, settings)
    if invalid:
        keys = "、".join(sorted(set(invalid)))
        text = f"⚠️ 以下字段或字段值无效，已拒绝: {keys}\n\n{text}"
    await update.effective_message.reply_text(
        text, reply_markup=anti_spam_config_keyboard(settings, target_chat_id)
    )


async def anti_spam_config_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, session: AsyncSession,
    *, state: ConversationState, message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = await _resolve_config_target(
        update, context, session, state=state
    )
    if target_chat_id is None:
        return
    await ModuleSettingsService.ensure(
        session, chat_id=target_chat_id,
        chat_type="supergroup" if target_chat_id < 0 else "private",
        user_id=update.effective_user.id,
    )
    settings = await get_chat_settings(session, target_chat_id)
    updates, rules, invalid = _parse_config_text(
        message_text, get_antispam_rules(settings)
    )
    for field, value in updates.items():
        setattr(settings, field, value)
    cleaned_rules = copy.deepcopy(DEFAULT_RULES)
    cleaned_rules.update({key: value for key, value in rules.items() if key in cleaned_rules})
    settings.anti_spam_rules = cleaned_rules
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    await session.commit()
    await _reply_config_result(
        update, context, target_chat_id=target_chat_id,
        settings=settings, invalid=invalid,
    )
