from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ==================== 格式化函数 ====================


def format_verification_menu_text(
    chat_title: str,
    verification_mode: str,
    timeout_seconds: int,
    restrict_can_send: bool,
) -> str:
    """
    格式化验证菜单文本

    Args:
        chat_title: 群组标题
        verification_mode: 验证模式
        timeout_seconds: 超时时间（秒）
        restrict_can_send: 是否限制发言

    Returns:
        格式化后的验证菜单文本
    """
    mode_labels = {
        "button": "🔘 按钮验证",
        "math": "🔢 数学题验证",
        "captcha": "🔢 验证码验证",
    }
    mode_label = mode_labels.get(verification_mode, verification_mode)

    text = f"🤖 [{chat_title}] 新人验证\n\n"
    text += f"当前验证模式: {mode_label}\n"
    text += f"超时时间: {timeout_seconds} 秒\n"
    text += f"限制发言: {'是' if restrict_can_send else '否'}\n\n"
    text += f"💡 点击下方按钮切换验证模式"
    return text


def format_admin_main_menu_text(chat_title: str) -> str:
    """
    格式化管理主菜单文本

    Args:
        chat_title: 群组标题

    Returns:
        格式化后的主菜单文本
    """
    text = f"🎛️ 群组管理\n\n"
    text += f"📍 当前群组: {chat_title}\n\n"
    text += f"请选择要管理的内容："
    return text


def create_group_selection_keyboard(
    managed_chats: list[tuple[int, str, bool]],
    current_chat_id: int | None,
) -> InlineKeyboardMarkup:
    """
    创建群组选择键盘

    Args:
        managed_chats: 管理的群组列表 [(chat_id, title, is_admin), ...]
        current_chat_id: 当前选中的群组ID

    Returns:
        群组选择键盘
    """
    buttons = []

    for chat_id, title, is_admin in managed_chats:
        is_current = "✅ " if chat_id == current_chat_id else ""
        buttons.append([
            InlineKeyboardButton(f"{is_current}{title}", callback_data=f"adm:select_group:{chat_id}")
        ])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:back_to_main")])

    return InlineKeyboardMarkup(buttons)


def create_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """
    创建引导按钮键盘

    Args:
        bot_username: 机器人用户名

    Returns:
        引导按钮键盘
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{bot_username}")],
    ])


def admin_main_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """管理员主菜单（参考 WeGroupBot 样式）

    Args:
        chat_id: 群组ID，用于私聊管理场景。如果提供，callback_data 会包含 chat_id
    """
    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        # 第一行：功能入口
        buttons = [
            [
                InlineKeyboardButton("🎁抽奖", callback_data=f"adm:menu:lottery:{chat_id}"),
                InlineKeyboardButton("🔗邀请链接", callback_data=f"adm:menu:invite:{chat_id}"),
            ],
            [
                InlineKeyboardButton("📋接龙", callback_data=f"adm:menu:solitaire:{chat_id}"),
                InlineKeyboardButton("📢广告", callback_data=f"adm:menu:ads:{chat_id}"),
            ],
            [
                InlineKeyboardButton("💬自动回复", callback_data=f"adm:menu:autoreply:{chat_id}"),
                InlineKeyboardButton("⏰定时消息", callback_data=f"adm:menu:scheduled:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔇违禁词", callback_data=f"adm:menu:keywords:{chat_id}"),
                InlineKeyboardButton("💰积分", callback_data=f"adm:menu:points:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🧹自动删除", callback_data=f"adm:menu:autodel:{chat_id}"),
                InlineKeyboardButton("🤖验证", callback_data=f"adm:menu:verification:{chat_id}"),
            ],
            # 快捷设置开关（常用功能）
            [
                InlineKeyboardButton("🔄切换群组", callback_data="adm:switch_group"),
                InlineKeyboardButton("🔙返回", callback_data=f"adm:back_to_main"),
            ],
        ]
        return InlineKeyboardMarkup(buttons)
    # 群聊场景：原格式
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎁抽奖", callback_data="adm:menu:lottery"),
                InlineKeyboardButton("🔗邀请链接", callback_data="adm:menu:invite"),
            ],
            [
                InlineKeyboardButton("👋欢迎", callback_data="adm:menu:welcome"),
                InlineKeyboardButton("🤖验证", callback_data="adm:menu:verification"),
            ],
            [
                InlineKeyboardButton("💬自动回复", callback_data="adm:menu:autoreply"),
                InlineKeyboardButton("⏰定时消息", callback_data="adm:menu:scheduled"),
            ],
            [
                InlineKeyboardButton("🚫反垃圾", callback_data="adm:menu:antispam"),
                InlineKeyboardButton("🔇违禁词", callback_data="adm:menu:keywords"),
            ],
            [
                InlineKeyboardButton("💰积分", callback_data="adm:menu:points"),
                InlineKeyboardButton("📊统计", callback_data="adm:menu:stats"),
            ],
            [
                InlineKeyboardButton("⚙️群设置", callback_data="adm:menu:settings"),
            ],
        ]
    )


def back_button(to_menu: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"adm:menu:{to_menu}")]])


def toggle_menu(rows: list[tuple[str, str, bool]], back_to: str) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for label, key, enabled in rows:
        prefix = "✅" if enabled else "❌"
        kb.append([InlineKeyboardButton(f"{prefix} {label}", callback_data=f"adm:toggle:{key}")])
    kb.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:{back_to}")])
    return InlineKeyboardMarkup(kb)


def verification_mode_menu(current_mode: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """验证模式选择菜单

    Args:
        current_mode: 当前验证模式
        chat_id: 群组ID，用于私聊管理场景
    """
    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        back_callback = f"adm:menu:main:{chat_id}"
        button_callbacks = [
            f"adm:vfy_mode:{chat_id}:button",
            f"adm:vfy_mode:{chat_id}:math",
            f"adm:vfy_mode:{chat_id}:captcha",
        ]
    else:
        # 群聊场景：原格式
        back_callback = "adm:menu:verification"
        button_callbacks = [
            "adm:vfy_mode:button",
            "adm:vfy_mode:math",
            "adm:vfy_mode:captcha",
        ]

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔘 按钮验证", callback_data=button_callbacks[0])],
            [InlineKeyboardButton("🔢 数学题验证", callback_data=button_callbacks[1])],
            [InlineKeyboardButton("🔢 验证码验证", callback_data=button_callbacks[2])],
            [InlineKeyboardButton("返回", callback_data=back_callback)],
        ]
    )





