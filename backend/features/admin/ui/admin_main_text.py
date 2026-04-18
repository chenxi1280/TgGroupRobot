from __future__ import annotations

from backend.features.group_ops.services.group_daily_stats import (
    ANNOUNCEMENT_LINK_TEXT,
    AdminMenuStats,
)


def format_verification_menu_text(
    chat_title: str,
    enabled: bool,
    verification_mode: str,
    timeout_seconds: int,
    restrict_can_send: bool,
    timeout_action: str,
    mute_duration: int,
) -> str:
    mode_label = {
        "button": "📄 简单接受条约",
        "math": "🔢 简单加减法",
        "mute": "🤐 直接禁言新人",
        "captcha": "🔑 验证码验证",
        "admin": "👤 管理员确认",
    }.get(verification_mode, verification_mode)
    action_label = {"none": "不额外处理", "mute": "🔇 禁言", "kick": "👢 踢出"}.get(timeout_action, timeout_action)
    status_label = "✅ 开启" if enabled else "❌ 关闭"

    text = f"🤖 [{chat_title}] 新人验证设置\n\n"
    text += f"状态: {status_label}\n"
    text += f"验证方式: {mode_label}\n"
    text += f"超时时间: {timeout_seconds} 秒\n"
    text += f"超时处理: {action_label}\n"
    if timeout_action == "mute":
        text += f"禁言时长: {mute_duration} 秒\n"
    text += f"限制发言: {'是' if restrict_can_send else '否'}\n\n"
    text += "💡 点击下方按钮进行配置"
    return text


def _format_day_line(label: str, counts) -> str:
    return f"{label}：加入({counts.joins}) 离开({counts.leaves}) 签到({counts.signs})"


def format_admin_main_menu_text(chat_title: str, menu_stats: AdminMenuStats | None = None) -> str:
    if menu_stats is None:
        return f"🎛️ 群组管理\n\n📍 当前群组: {chat_title}\n\n请选择要管理的内容："

    lines = [
        "🎛️ 群组管理",
        "",
        f"正在管理【{chat_title}】",
        "",
        _format_day_line("今日", menu_stats.today),
        _format_day_line("昨日", menu_stats.yesterday),
        "",
    ]
    announcement_text = getattr(menu_stats, "announcement_text", ANNOUNCEMENT_LINK_TEXT)
    if announcement_text:
        lines.extend([announcement_text, ""])
    lines.extend(
        [
            f"有效期至：{menu_stats.expires_at_text}",
            "",
            "请选择要管理的内容：",
        ]
    )
    return "\n".join(lines)
