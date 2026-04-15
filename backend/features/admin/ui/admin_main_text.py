from __future__ import annotations


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


def format_admin_main_menu_text(chat_title: str) -> str:
    return f"🎛️ 群组管理\n\n📍 当前群组: {chat_title}\n\n请选择要管理的内容："
