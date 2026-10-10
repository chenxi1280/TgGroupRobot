from __future__ import annotations

from telegram import InlineKeyboardButton

from backend.features.admin.ui.antispam_controls import setting_row


def quick_reply_trigger_summary(rule: dict) -> str:
    mute_keyword = str(rule.get("mute_keyword", "j"))
    kick_keyword = str(rule.get("kick_keyword", "t"))
    return f"实际触发条件: 管理员引用成员消息后回复 {mute_keyword} 禁言，回复 {kick_keyword} 踢出"


def quick_reply_condition_rows(rule: dict, chat_id: int, rule_id: str) -> list[list[InlineKeyboardButton]]:
    return [
        setting_row("⚙️ 禁言回复词:", f"gg:input:{rule_id}:mute_keyword:{chat_id}", str(rule.get("mute_keyword", "j"))),
        setting_row("⚙️ 踢出回复词:", f"gg:input:{rule_id}:kick_keyword:{chat_id}", str(rule.get("kick_keyword", "t"))),
    ]


def quick_reply_action_rows(
    rule: dict,
    chat_id: int,
    rule_id: str,
    *, mute_seconds_label: str,
) -> list[list[InlineKeyboardButton]]:
    rows = [
        setting_row("⚙️ 删除指令:", f"gg:toggle:{rule_id}:delete_message:{chat_id}", _status(bool(rule.get("delete_message"))), enabled=bool(rule.get("delete_message"))),
        setting_row("⚙️ 禁言时长:", f"gg:cycle:{rule_id}:mute_seconds:{chat_id}", mute_seconds_label),
        _notice_row(rule, chat_id, rule_id),
    ]
    if bool(rule.get("notice_enabled")):
        rows.append(_notice_delete_row(rule, chat_id, rule_id))
    rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"gg:home:{chat_id}")])
    return rows




def _status(enabled: bool) -> str:
    return "✅ 启动" if enabled else "❌ 关闭"


def _notice_row(rule: dict, chat_id: int, rule_id: str) -> list[InlineKeyboardButton]:
    notice_label = f"{rule['notice_delete_seconds']}秒后删除" if bool(rule.get("notice_enabled")) else "❌ 关闭"
    return setting_row("⚙️ 提示消息:", f"gg:toggle:{rule_id}:notice_enabled:{chat_id}", notice_label, enabled=bool(rule.get("notice_enabled")))


def _notice_delete_row(rule: dict, chat_id: int, rule_id: str) -> list[InlineKeyboardButton]:
    return setting_row("⚙️ 提示删除:", f"gg:cycle:{rule_id}:notice_delete_seconds:{chat_id}", f"{rule['notice_delete_seconds']}秒")
