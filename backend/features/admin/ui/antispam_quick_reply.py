from __future__ import annotations

from telegram import InlineKeyboardButton


def quick_reply_trigger_summary(rule: dict) -> str:
    mute_keyword = str(rule.get("mute_keyword", "j"))
    kick_keyword = str(rule.get("kick_keyword", "t"))
    return f"实际触发条件: 管理员引用成员消息后回复 {mute_keyword} 禁言，回复 {kick_keyword} 踢出"


def quick_reply_condition_rows(rule: dict, chat_id: int, rule_id: str) -> list[list[InlineKeyboardButton]]:
    return [
        _two_button_row(
            "⚙️ 禁言回复词:",
            f"gg:input:{rule_id}:mute_keyword:{chat_id}",
            str(rule.get("mute_keyword", "j")),
            right_callback=f"gg:input:{rule_id}:mute_keyword:{chat_id}",
        ),
        _two_button_row(
            "⚙️ 踢出回复词:",
            f"gg:input:{rule_id}:kick_keyword:{chat_id}",
            str(rule.get("kick_keyword", "t")),
            right_callback=f"gg:input:{rule_id}:kick_keyword:{chat_id}",
        ),
    ]


def quick_reply_action_rows(
    rule: dict,
    chat_id: int,
    rule_id: str,
    *, mute_seconds_label: str,
) -> list[list[InlineKeyboardButton]]:
    rows = [
        _two_button_row(
            "⚙️ 删除指令:",
            f"gg:toggle:{rule_id}:delete_message:{chat_id}",
            _status(bool(rule.get("delete_message"))),
            right_callback=f"gg:toggle:{rule_id}:delete_message:{chat_id}",
        ),
        _two_button_row(
            "⚙️ 禁言时长:",
            f"gg:cycle:{rule_id}:mute_seconds:{chat_id}",
            mute_seconds_label,
            right_callback=f"gg:cycle:{rule_id}:mute_seconds:{chat_id}",
        ),
        _notice_row(rule, chat_id, rule_id),
    ]
    if bool(rule.get("notice_enabled")):
        rows.append(_notice_delete_row(rule, chat_id, rule_id))
    rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"gg:home:{chat_id}")])
    return rows


def _two_button_row(
    left_text: str,
    left_callback: str,
    right_text: str,
    *, right_callback: str,
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(left_text, callback_data=left_callback),
        InlineKeyboardButton(right_text, callback_data=right_callback),
    ]


def _status(enabled: bool) -> str:
    return "✅ 启动" if enabled else "❌ 关闭"


def _notice_row(rule: dict, chat_id: int, rule_id: str) -> list[InlineKeyboardButton]:
    notice_label = f"{rule['notice_delete_seconds']}秒后删除" if bool(rule.get("notice_enabled")) else "❌ 关闭"
    return _two_button_row(
        "⚙️ 提示消息:",
        f"gg:toggle:{rule_id}:notice_enabled:{chat_id}",
        notice_label,
        right_callback=f"gg:toggle:{rule_id}:notice_enabled:{chat_id}",
    )


def _notice_delete_row(rule: dict, chat_id: int, rule_id: str) -> list[InlineKeyboardButton]:
    return _two_button_row(
        "⚙️ 提示删除:",
        f"gg:cycle:{rule_id}:notice_delete_seconds:{chat_id}",
        f"{rule['notice_delete_seconds']}秒",
        right_callback=f"gg:cycle:{rule_id}:notice_delete_seconds:{chat_id}",
    )
