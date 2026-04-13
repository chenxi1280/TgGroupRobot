from __future__ import annotations

import copy

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.ui.antispam import anti_spam_config_keyboard
from backend.features.moderation.anti_spam_config_presenter import format_anti_spam_menu_text
from backend.features.moderation.anti_spam_config_utils import _parse_bool, _parse_int, _resolve_target_chat_id, _split_int_list, _split_list
from backend.features.moderation.services.anti_spam_service import DEFAULT_RULES, get_antispam_rules
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ConversationState
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService


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
    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    chat_title = await handler._get_chat_title(db, target_chat_id)
    text = "✅ 反垃圾配置已更新\n\n" + format_anti_spam_menu_text(chat_title, settings)
    if invalid_keys:
        keys = "、".join(sorted(set(invalid_keys)))
        text = f"⚠️ 以下字段值无效，已忽略: {keys}\n\n{text}"
    keyboard = anti_spam_config_keyboard(settings, target_chat_id)
    await update.effective_message.reply_text(text, reply_markup=keyboard)
