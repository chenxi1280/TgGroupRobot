"""垃圾防护配置键盘"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.moderation.services.garbage_guard_rules import (
    RULE_DEFINITIONS,
    RULE_ORDER,
    get_garbage_config,
    get_global_whitelist_user_ids,
    get_rule_config,
)


def _status(enabled: bool) -> str:
    return "✅ 启动" if enabled else "❌ 关闭"


def _short_status(enabled: bool) -> str:
    return "✅" if enabled else "❌"


def _seconds_label(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds // 86400}天"
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600}小时"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}分钟"
    return f"{seconds}秒"


def _rule_button_text(settings, rule_id: str) -> str:
    rule = get_rule_config(settings, rule_id)
    return f"{_short_status(bool(rule.get('enabled')))} {RULE_DEFINITIONS[rule_id].label}"


def garbage_guard_home_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pairs = [
        ("banned_words", "long_message"),
        ("long_name", "block_links"),
        ("block_buttons", "spam_user"),
        ("block_forwards", "flood"),
        ("manual_warning", "leave_ban"),
    ]
    for left, right in pairs:
        rows.append(
            [
                InlineKeyboardButton(_rule_button_text(settings, left), callback_data=f"gg:rule:{left}:{chat_id}"),
                InlineKeyboardButton(_rule_button_text(settings, right), callback_data=f"gg:rule:{right}:{chat_id}"),
            ]
        )

    whitelist_count = len(get_global_whitelist_user_ids(settings))
    rows.append(
        [
            InlineKeyboardButton(
                f"📄 总白名单管理（{whitelist_count}人，所有规则生效）",
                callback_data=f"gg:whitelist:{chat_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def format_garbage_guard_home_text(chat_title: str, settings) -> str:
    config = get_garbage_config(settings)
    enabled_count = sum(1 for rule_id in RULE_ORDER if bool(config["rules"][rule_id].get("enabled")))
    return "\n".join(
        [
            f"☂️ [{chat_title}] 垃圾防护功能",
            "",
            "拦截违禁词 - 匹配到违禁词时进行处罚",
            "禁止长内容 - 消息长度超过配置限额处罚",
            "禁止长昵称 - 昵称字数超限额发言时处罚",
            "禁止转发引用 - 用户转发或引用会被处罚",
            "禁止发送按钮 - 当用户消息含按钮时处罚",
            "禁止垃圾用户 - 无用户名或外文昵称用户",
            "禁止发言刷屏 - 短时间大量发言进行处罚",
            "",
            "以上规则对管理员和白名单用户无效",
            "",
            f"已启动规则: {enabled_count}/{len(RULE_ORDER)}",
        ]
    )


def _condition_rows(settings, chat_id: int, rule_id: str, banned_word_count: int = 0) -> list[list[InlineKeyboardButton]]:
    rule = get_rule_config(settings, rule_id)
    if rule_id == "banned_words":
        return [
            [
                InlineKeyboardButton("⚙️ 检测条件:", callback_data=f"banned_word:list:{chat_id}"),
                InlineKeyboardButton(f"{banned_word_count} 个违禁词", callback_data=f"banned_word:list:{chat_id}"),
            ]
        ]
    if rule_id == "long_message":
        return [
            [
                InlineKeyboardButton("⚙️ 内容长度:", callback_data=f"gg:cycle:{rule_id}:message_max_length:{chat_id}"),
                InlineKeyboardButton(f"{rule['message_max_length']} 字", callback_data=f"gg:cycle:{rule_id}:message_max_length:{chat_id}"),
            ]
        ]
    if rule_id == "long_name":
        return [
            [
                InlineKeyboardButton("⚙️ 昵称长度:", callback_data=f"gg:cycle:{rule_id}:name_max_length:{chat_id}"),
                InlineKeyboardButton(f"{rule['name_max_length']} 字", callback_data=f"gg:cycle:{rule_id}:name_max_length:{chat_id}"),
            ]
        ]
    if rule_id == "spam_user":
        return [
            [
                InlineKeyboardButton("⚙️ 无用户名:", callback_data=f"gg:toggle:{rule_id}:check_no_username:{chat_id}"),
                InlineKeyboardButton(_status(bool(rule.get("check_no_username"))), callback_data=f"gg:toggle:{rule_id}:check_no_username:{chat_id}"),
            ],
            [
                InlineKeyboardButton("⚙️ 外文昵称:", callback_data=f"gg:toggle:{rule_id}:check_foreign_name:{chat_id}"),
                InlineKeyboardButton(_status(bool(rule.get("check_foreign_name"))), callback_data=f"gg:toggle:{rule_id}:check_foreign_name:{chat_id}"),
            ],
        ]
    if rule_id == "flood":
        return [
            [
                InlineKeyboardButton("⚙️ 触发条数:", callback_data=f"gg:cycle:{rule_id}:messages:{chat_id}"),
                InlineKeyboardButton(f"{rule['messages']} 条", callback_data=f"gg:cycle:{rule_id}:messages:{chat_id}"),
            ],
            [
                InlineKeyboardButton("⚙️ 时间窗口:", callback_data=f"gg:cycle:{rule_id}:seconds:{chat_id}"),
                InlineKeyboardButton(f"{rule['seconds']} 秒", callback_data=f"gg:cycle:{rule_id}:seconds:{chat_id}"),
            ],
        ]
    if rule_id == "manual_warning":
        return [
            [
                InlineKeyboardButton("⚙️ 警告词:", callback_data=f"gg:noop:{chat_id}"),
                InlineKeyboardButton("warn / 警告", callback_data=f"gg:noop:{chat_id}"),
            ]
        ]
    if rule_id == "leave_ban":
        return [
            [
                InlineKeyboardButton("⚙️ 离群动作:", callback_data=f"gg:noop:{chat_id}"),
                InlineKeyboardButton("自动封禁", callback_data=f"gg:noop:{chat_id}"),
            ]
        ]
    return [
        [
            InlineKeyboardButton("⚙️ 检测条件:", callback_data=f"gg:noop:{chat_id}"),
            InlineKeyboardButton("固定检测", callback_data=f"gg:noop:{chat_id}"),
        ]
    ]


def garbage_guard_rule_keyboard(settings, chat_id: int, rule_id: str, banned_word_count: int = 0) -> InlineKeyboardMarkup:
    rule = get_rule_config(settings, rule_id)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("⚙️ 状态:", callback_data=f"gg:toggle:{rule_id}:enabled:{chat_id}"),
            InlineKeyboardButton(_status(bool(rule.get("enabled"))), callback_data=f"gg:toggle:{rule_id}:enabled:{chat_id}"),
        ]
    ]
    rows.extend(_condition_rows(settings, chat_id, rule_id, banned_word_count))

    rows.append(
        [
            InlineKeyboardButton("⚙️ 删除消息:", callback_data=f"gg:toggle:{rule_id}:delete_message:{chat_id}"),
            InlineKeyboardButton(_status(bool(rule.get("delete_message"))), callback_data=f"gg:toggle:{rule_id}:delete_message:{chat_id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("⚙️ 警告成员:", callback_data=f"gg:toggle:{rule_id}:warn_enabled:{chat_id}"),
            InlineKeyboardButton(_status(bool(rule.get("warn_enabled"))), callback_data=f"gg:toggle:{rule_id}:warn_enabled:{chat_id}"),
        ]
    )
    if bool(rule.get("warn_enabled")):
        rows.append(
            [
                InlineKeyboardButton("⚙️ 警告次数:", callback_data=f"gg:cycle:{rule_id}:warn_threshold:{chat_id}"),
                InlineKeyboardButton(f"警告{rule['warn_threshold']}次", callback_data=f"gg:cycle:{rule_id}:warn_threshold:{chat_id}"),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton("⚙️ 禁言成员:", callback_data=f"gg:toggle:{rule_id}:mute_enabled:{chat_id}"),
            InlineKeyboardButton(_status(bool(rule.get("mute_enabled"))), callback_data=f"gg:toggle:{rule_id}:mute_enabled:{chat_id}"),
        ]
    )
    if bool(rule.get("mute_enabled")):
        rows.append(
            [
                InlineKeyboardButton("⚙️ 禁言时长:", callback_data=f"gg:cycle:{rule_id}:mute_seconds:{chat_id}"),
                InlineKeyboardButton(_seconds_label(int(rule["mute_seconds"])), callback_data=f"gg:cycle:{rule_id}:mute_seconds:{chat_id}"),
            ]
        )

    if rule_id != "leave_ban":
        rows.append(
            [
                InlineKeyboardButton("⚙️ 踢出成员:", callback_data=f"gg:toggle:{rule_id}:kick_enabled:{chat_id}"),
                InlineKeyboardButton(_status(bool(rule.get("kick_enabled"))), callback_data=f"gg:toggle:{rule_id}:kick_enabled:{chat_id}"),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton("⚙️ 提示消息:", callback_data=f"gg:toggle:{rule_id}:notice_enabled:{chat_id}"),
            InlineKeyboardButton(
                f"{rule['notice_delete_seconds']}秒后删除" if bool(rule.get("notice_enabled")) else "❌ 关闭",
                callback_data=f"gg:toggle:{rule_id}:notice_enabled:{chat_id}",
            ),
        ]
    )
    if bool(rule.get("notice_enabled")):
        rows.append(
            [
                InlineKeyboardButton("⚙️ 提示删除:", callback_data=f"gg:cycle:{rule_id}:notice_delete_seconds:{chat_id}"),
                InlineKeyboardButton(f"{rule['notice_delete_seconds']}秒", callback_data=f"gg:cycle:{rule_id}:notice_delete_seconds:{chat_id}"),
            ]
        )

    whitelist_count = len(get_global_whitelist_user_ids(settings))
    rows.append(
        [
            InlineKeyboardButton("⚙️ 白名单用户:", callback_data=f"gg:whitelist:{chat_id}"),
            InlineKeyboardButton(f"{whitelist_count}人", callback_data=f"gg:whitelist:{chat_id}"),
        ]
    )
    rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"gg:home:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def format_garbage_rule_text(chat_title: str, settings, rule_id: str) -> str:
    definition = RULE_DEFINITIONS[rule_id]
    rule = get_rule_config(settings, rule_id)
    return "\n".join(
        [
            f"{definition.title}",
            "",
            definition.description,
            "",
            f"状态: {'启动' if bool(rule.get('enabled')) else '关闭'}",
            f"白名单用户: {len(get_global_whitelist_user_ids(settings))}人",
            "",
            "管理员和总白名单用户不会触发本规则。",
        ]
    )


def garbage_guard_whitelist_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ 配置白名单", callback_data=f"gg:input:whitelist:{chat_id}")],
            [InlineKeyboardButton("🧹 清空白名单", callback_data=f"gg:clear:whitelist:{chat_id}")],
            [InlineKeyboardButton("⬅️ 返回", callback_data=f"gg:home:{chat_id}")],
        ]
    )


def format_garbage_whitelist_text(chat_title: str, settings) -> str:
    whitelist = get_global_whitelist_user_ids(settings)
    values = "\n".join(str(user_id) for user_id in whitelist) if whitelist else "暂无"
    return "\n".join(
        [
            f"📄 [{chat_title}] 总白名单管理",
            "",
            "白名单中的用户不受垃圾防护所有规则影响。",
            "",
            f"当前人数: {len(whitelist)}",
            values,
        ]
    )


def anti_flood_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    return garbage_guard_rule_keyboard(settings, chat_id, "flood")


def anti_spam_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    return garbage_guard_home_keyboard(settings, chat_id)
