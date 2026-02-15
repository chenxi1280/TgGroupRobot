"""防刷屏与反垃圾配置键盘"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.moderation.anti_spam_service import get_antispam_rules


def _status(enabled: bool) -> str:
    return "✅ 开启" if enabled else "❌ 关闭"


def anti_flood_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"防刷屏: {_status(settings.anti_flood_enabled)}", callback_data=f"afcfg:toggle:enabled:{chat_id}")],
        [
            InlineKeyboardButton(f"触发条数: {settings.anti_flood_messages}", callback_data=f"afcfg:cycle:messages:{chat_id}"),
            InlineKeyboardButton(f"时间窗口: {settings.anti_flood_seconds}s", callback_data=f"afcfg:cycle:seconds:{chat_id}"),
        ],
        [
            InlineKeyboardButton(f"惩罚动作: {settings.anti_flood_action}", callback_data=f"afcfg:cycle:action:{chat_id}"),
            InlineKeyboardButton(f"禁言时长: {settings.anti_flood_mute_duration}s", callback_data=f"afcfg:cycle:mute:{chat_id}"),
        ],
        [
            InlineKeyboardButton(
                f"管理员豁免: {_status(settings.anti_flood_exempt_admin)}",
                callback_data=f"afcfg:toggle:admin_exempt:{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(
                f"触发后清理消息: {_status(settings.anti_flood_cleanup_messages)}",
                callback_data=f"afcfg:toggle:cleanup:{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(
                f"删除提醒: {_status(settings.anti_flood_delete_notify)}",
                callback_data=f"afcfg:toggle:notify:{chat_id}",
            ),
            InlineKeyboardButton(
                f"提醒保留: {settings.anti_flood_delete_notify_seconds}s",
                callback_data=f"afcfg:cycle:notify_sec:{chat_id}",
            ),
        ],
        [InlineKeyboardButton("📝 文本配置", callback_data=f"adm:af_config:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ])


def anti_spam_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    rules = get_antispam_rules(settings)

    rule_buttons = [
        ("ai_text", "AI文本", "ait"),
        ("global_ads", "广告拦截", "gad"),
        ("flood_attack", "反洪水", "fld"),
        ("banned_accounts", "封禁账号", "ban"),
        ("ai_image_ads", "AI图片广告", "aig"),
        ("block_links", "屏蔽链接", "lnk"),
        ("block_channel_alias", "频道马甲", "als"),
        ("block_forwards", "拦截转发", "fwd"),
        ("block_mentions", "拦截@对象", "men"),
        ("block_eth_address", "ETH地址", "eth"),
        ("clear_commands", "清理命令", "cmd"),
        ("block_long_content", "超长内容", "lng"),
    ]

    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(f"反垃圾: {_status(settings.anti_spam_enabled)}", callback_data=f"ascfg:toggle:enabled:{chat_id}")],
        [
            InlineKeyboardButton(f"惩罚动作: {settings.anti_spam_action}", callback_data=f"ascfg:cycle:action:{chat_id}"),
            InlineKeyboardButton(f"禁言: {settings.anti_spam_mute_duration}s", callback_data=f"ascfg:cycle:mute:{chat_id}"),
        ],
        [
            InlineKeyboardButton(
                f"管理员豁免: {_status(settings.anti_spam_exempt_admin)}",
                callback_data=f"ascfg:toggle:admin_exempt:{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(f"删除提醒: {_status(settings.anti_spam_delete_notify)}", callback_data=f"ascfg:toggle:notify:{chat_id}"),
            InlineKeyboardButton(f"提醒保留: {settings.anti_spam_delete_notify_seconds}s", callback_data=f"ascfg:cycle:notify_sec:{chat_id}"),
        ],
        [
            InlineKeyboardButton(f"重复阈值: {settings.anti_spam_repeat_messages}", callback_data=f"ascfg:cycle:repeat_msgs:{chat_id}"),
            InlineKeyboardButton(f"检测窗口: {settings.anti_spam_repeat_seconds}s", callback_data=f"ascfg:cycle:repeat_sec:{chat_id}"),
        ],
    ]

    for key, label, code in rule_buttons:
        buttons.append([
            InlineKeyboardButton(
                f"{label}: {_status(bool(rules.get(key)))}",
                callback_data=f"ascfg:rule:{code}:{chat_id}",
            )
        ])

    buttons.extend([
        [InlineKeyboardButton("📝 文本配置(名单/阈值)", callback_data=f"adm:as_config:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ])

    return InlineKeyboardMarkup(buttons)
