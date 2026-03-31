"""管理员主菜单键盘

提供管理员主菜单、验证模式选择等功能。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def format_verification_menu_text(
    chat_title: str,
    enabled: bool,
    verification_mode: str,
    timeout_seconds: int,
    restrict_can_send: bool,
    timeout_action: str,
    mute_duration: int,
) -> str:
    """格式化验证菜单文本

    Args:
        chat_title: 群组标题
        enabled: 是否启用验证
        verification_mode: 验证模式
        timeout_seconds: 超时时间（秒）
        restrict_can_send: 是否限制发言
        timeout_action: 超时处理动作
        mute_duration: 禁言时长（秒）

    Returns:
        格式化后的验证菜单文本
    """
    mode_labels = {
        "button": "🔘 按钮验证",
        "math": "🔢 数学题验证",
        "captcha": "🔑 验证码验证",
        "admin": "👤 管理员确认",
    }
    mode_label = mode_labels.get(verification_mode, verification_mode)

    action_labels = {
        "mute": "🔇 禁言",
        "kick": "👢 踢出",
    }
    action_label = action_labels.get(timeout_action, timeout_action)

    status_label = "✅ 开启" if enabled else "❌ 关闭"

    text = f"🤖 [{chat_title}] 新人验证设置\n\n"
    text += f"状态: {status_label}\n"
    text += f"验证方式: {mode_label}\n"
    text += f"超时时间: {timeout_seconds} 秒\n"
    text += f"超时处理: {action_label}\n"
    if timeout_action == "mute":
        text += f"禁言时长: {mute_duration} 秒\n"
    text += f"限制发言: {'是' if restrict_can_send else '否'}\n\n"
    text += f"💡 点击下方按钮进行配置"
    return text


def format_admin_main_menu_text(chat_title: str) -> str:
    """格式化管理主菜单文本

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
    """创建群组选择键盘

    Args:
        managed_chats: 管理的群组列表 [(chat_id, title, is_admin), ...]
        current_chat_id: 当前选中的群组 ID

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
    """创建引导按钮键盘

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
        chat_id: 群组 ID，用于私聊管理场景。如果提供，callback_data 会包含 chat_id
    """
    if chat_id is not None:
        # 私聊管理场景：按新版样式重排，callback_data 包含 chat_id
        buttons = [
            [
                InlineKeyboardButton("🎠轮播广告", callback_data=f"adm:menu:ads:{chat_id}"),
                InlineKeyboardButton("💬自动回复", callback_data=f"adm:menu:autoreply:{chat_id}"),
                InlineKeyboardButton("⏰定时消息", callback_data=f"sm:list:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🚗车库认证", callback_data=f"adm:menu:garage_auth:{chat_id}"),
                InlineKeyboardButton("🔍老师搜索", callback_data=f"adm:menu:teacher_search:{chat_id}"),
                InlineKeyboardButton("↔️车库转发", callback_data=f"adm:menu:garage_forward:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🌑主积分", callback_data=f"adm:menu:points:{chat_id}"),
                InlineKeyboardButton("🌐自定义积分", callback_data=f"adm:menu:custom_points:{chat_id}"),
                InlineKeyboardButton("🧑‍🎓积分等级", callback_data=f"adm:menu:points_level:{chat_id}"),
            ],
            [
                InlineKeyboardButton("💰拍卖", callback_data=f"adm:menu:auction:{chat_id}"),
                InlineKeyboardButton("🎁抽奖", callback_data=f"adm:menu:lottery:{chat_id}"),
                InlineKeyboardButton("🎮游戏", callback_data=f"adm:menu:game:{chat_id}"),
                InlineKeyboardButton("⚽竞猜", callback_data=f"adm:menu:guess:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔗邀请链接", callback_data=f"adm:menu:invite:{chat_id}"),
                InlineKeyboardButton("🎉进群欢迎", callback_data=f"adm:menu:welcome:{chat_id}"),
                InlineKeyboardButton("🛡️进群验证", callback_data=f"adm:menu:verification:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🌊防刷屏", callback_data=f"adm:menu:flood:{chat_id}"),
                InlineKeyboardButton("✨促活工具", callback_data=f"adm:menu:engagement:{chat_id}"),
                InlineKeyboardButton("☂️反垃圾", callback_data=f"adm:menu:antispam:{chat_id}"),
                InlineKeyboardButton("🧨关群设置", callback_data=f"adm:menu:closegroup:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🕵️改名监控", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton("💥炸号继承", callback_data=f"adm:menu:inherit:{chat_id}"),
                InlineKeyboardButton("🛡️联盟功能", callback_data=f"adm:menu:alliance:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🛒积分商城", callback_data=f"adm:menu:points_mall:{chat_id}"),
                InlineKeyboardButton("💯车评系统", callback_data=f"adm:menu:car_review:{chat_id}"),
                InlineKeyboardButton("⌨️底部按钮", callback_data=f"adm:menu:bottom_button:{chat_id}"),
            ],
            [
                InlineKeyboardButton("📣强制订阅", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton("🧹删除提示", callback_data=f"adm:menu:autodel:{chat_id}"),
                InlineKeyboardButton("⚙️控制权限", callback_data=f"adm:menu:control:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔐续费入口", callback_data=f"adm:menu:renewal:{chat_id}"),
                InlineKeyboardButton("🔄切换群", callback_data="adm:switch_group"),
            ],
        ]
        return InlineKeyboardMarkup(buttons)

    # 群聊场景：原格式
    return InlineKeyboardMarkup([
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
            InlineKeyboardButton("🧩自定义积分", callback_data="adm:menu:custom_points"),
            InlineKeyboardButton("👑积分等级", callback_data="adm:menu:points_level"),
        ],
        [
            InlineKeyboardButton("🛍积分商城", callback_data="adm:menu:points_mall"),
        ],
        [
            InlineKeyboardButton("🖐联盟功能", callback_data="adm:menu:alliance"),
            InlineKeyboardButton("🔁车库转发", callback_data="adm:menu:garage_forward"),
        ],
        [
            InlineKeyboardButton("🚗车库认证", callback_data="adm:menu:garage_auth"),
            InlineKeyboardButton("🔎老师搜索", callback_data="adm:menu:teacher_search"),
        ],
        [InlineKeyboardButton("💯车评系统", callback_data="adm:menu:car_review")],
        [InlineKeyboardButton("⚙️群设置", callback_data="adm:menu:settings")],
    ])


def back_button(to_menu: str = "main") -> InlineKeyboardMarkup:
    """返回按钮"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{to_menu}")]])


def toggle_menu(rows: list[tuple[str, str, bool]], back_to: str) -> InlineKeyboardMarkup:
    """开关菜单"""
    kb: list[list[InlineKeyboardButton]] = []
    for label, key, enabled in rows:
        prefix = "✅" if enabled else "❌"
        kb.append([InlineKeyboardButton(f"{prefix} {label}", callback_data=f"adm:toggle:{key}")])
    kb.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{back_to}")])
    return InlineKeyboardMarkup(kb)


def verification_mode_menu(current_mode: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """验证模式选择菜单

    Args:
        current_mode: 当前验证模式
        chat_id: 群组 ID，用于私聊管理场景
    """
    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        back_callback = f"adm:menu:main:{chat_id}"
        button_callbacks = [
            f"adm:vfy_mode:{chat_id}:button",
            f"adm:vfy_mode:{chat_id}:math",
            f"adm:vfy_mode:{chat_id}:captcha",
            f"adm:vfy_mode:{chat_id}:admin",
        ]
    else:
        # 群聊场景：原格式
        back_callback = "adm:menu:verification"
        button_callbacks = [
            "adm:vfy_mode:button",
            "adm:vfy_mode:math",
            "adm:vfy_mode:captcha",
            "adm:vfy_mode:admin",
        ]

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 按钮验证", callback_data=button_callbacks[0])],
        [InlineKeyboardButton("🔢 数学题验证", callback_data=button_callbacks[1])],
        [InlineKeyboardButton("🔑 验证码验证", callback_data=button_callbacks[2])],
        [InlineKeyboardButton("👤 管理员确认", callback_data=button_callbacks[3])],
        [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
    ])


def verification_config_menu(
    enabled: bool,
    mode: str,
    timeout_seconds: int,
    timeout_action: str,
    restrict_can_send: bool,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """验证配置菜单

    Args:
        enabled: 是否启用验证
        mode: 验证模式
        timeout_seconds: 超时时间（秒）
        timeout_action: 超时处理动作
        restrict_can_send: 是否限制发言
        chat_id: 群组 ID，用于私聊管理场景
    """
    status_prefix = "✅" if enabled else "❌"
    mode_label = {
        "button": "按钮验证",
        "math": "数学题",
        "captcha": "验证码",
        "admin": "管理员",
    }.get(mode, mode)

    action_label = {
        "mute": "禁言",
        "kick": "踢出",
    }.get(timeout_action, timeout_action)

    restrict_prefix = "✅" if restrict_can_send else "❌"

    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        back_callback = f"adm:menu:main:{chat_id}"
        buttons = [
            [InlineKeyboardButton(f"{status_prefix} 验证开关", callback_data=f"adm:vfy_toggle:{chat_id}")],
            [InlineKeyboardButton(f"🔘 验证方式: {mode_label}", callback_data=f"adm:vfy_mode_menu:{chat_id}")],
            [InlineKeyboardButton(f"⏱️ 超时时间: {timeout_seconds}秒", callback_data=f"adm:vfy_timeout:{chat_id}")],
            [InlineKeyboardButton(f"🔇 超时处理: {action_label}", callback_data=f"adm:vfy_action:{chat_id}")],
            [InlineKeyboardButton(f"{restrict_prefix} 限制发言", callback_data=f"adm:vfy_restrict:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]
    else:
        # 群聊场景：原格式
        back_callback = "adm:menu:verification"
        buttons = [
            [InlineKeyboardButton(f"{status_prefix} 验证开关", callback_data="adm:vfy_toggle")],
            [InlineKeyboardButton(f"🔘 验证方式: {mode_label}", callback_data="adm:vfy_mode_menu")],
            [InlineKeyboardButton(f"⏱️ 超时时间: {timeout_seconds}秒", callback_data="adm:vfy_timeout")],
            [InlineKeyboardButton(f"🔇 超时处理: {action_label}", callback_data="adm:vfy_action")],
            [InlineKeyboardButton(f"{restrict_prefix} 限制发言", callback_data="adm:vfy_restrict")],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]

    return InlineKeyboardMarkup(buttons)


def verification_timeout_action_menu(current_action: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """验证超时处理动作选择菜单

    Args:
        current_action: 当前超时处理动作
        chat_id: 群组 ID，用于私聊管理场景
    """
    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        back_callback = f"adm:vfy_config:{chat_id}"
        button_callbacks = [
            f"adm:vfy_action:{chat_id}:mute",
            f"adm:vfy_action:{chat_id}:kick",
        ]
    else:
        # 群聊场景：原格式
        back_callback = "adm:vfy_config"
        button_callbacks = [
            "adm:vfy_action:mute",
            "adm:vfy_action:kick",
        ]

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔇 禁言", callback_data=button_callbacks[0])],
        [InlineKeyboardButton("👢 踢出群聊", callback_data=button_callbacks[1])],
        [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
    ])
