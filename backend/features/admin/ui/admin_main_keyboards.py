from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def create_group_selection_keyboard(
    managed_chats: list[tuple[int, str, bool]],
    current_chat_id: int | None,
) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"{'✅ ' if chat_id == current_chat_id else ''}{title}", callback_data=f"adm:select_group:{chat_id}")]
        for chat_id, title, _ in managed_chats
    ]
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="adm:back_to_main")])
    return InlineKeyboardMarkup(buttons)


def create_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{bot_username}")]])


def admin_main_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        buttons = [
            [
                InlineKeyboardButton("🎠轮播广告", callback_data=f"adm:menu:ads:{chat_id}"),
                InlineKeyboardButton("💬自动回复", callback_data=f"adm:menu:autoreply:{chat_id}"),
                InlineKeyboardButton("⏰定时消息", callback_data=f"sm:list:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🚗车库认证", callback_data=f"adm:menu:garage_auth:{chat_id}"),
                InlineKeyboardButton("🔍老师搜索", callback_data=f"adm:menu:teacher_search:{chat_id}"),
                InlineKeyboardButton("📡频道同步", callback_data=f"adm:menu:sync:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🌑主积分", callback_data=f"adm:menu:points:{chat_id}"),
                InlineKeyboardButton("🌐自定义积分", callback_data=f"adm:menu:custom_points:{chat_id}"),
                InlineKeyboardButton("🧑‍🎓积分等级", callback_data=f"adm:menu:points_level:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🛒积分商城", callback_data=f"adm:menu:points_mall:{chat_id}"),
                InlineKeyboardButton("💯车评系统", callback_data=f"adm:menu:car_review:{chat_id}"),
                InlineKeyboardButton("⌨️底部按钮", callback_data=f"adm:menu:bottom_button:{chat_id}"),
            ],
            [
                InlineKeyboardButton("💰拍卖", callback_data=f"adm:menu:auction:{chat_id}"),
                InlineKeyboardButton("🎁抽奖", callback_data=f"adm:menu:lottery:{chat_id}"),
                InlineKeyboardButton("✨促活工具", callback_data=f"adm:menu:engagement:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🎮游戏", callback_data=f"adm:menu:game:{chat_id}"),
                InlineKeyboardButton("⚽竞猜", callback_data=f"adm:menu:guess:{chat_id}"),
                InlineKeyboardButton("🔗邀请链接", callback_data=f"adm:menu:invite:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🎉进群欢迎", callback_data=f"adm:menu:welcome:{chat_id}"),
                InlineKeyboardButton("🛡️进群验证", callback_data=f"adm:menu:verification:{chat_id}"),
                InlineKeyboardButton("🧑‍🍼新成员限制", callback_data=f"adm:menu:newmem:{chat_id}"),
            ],
            [
                InlineKeyboardButton("☂️垃圾防护", callback_data=f"adm:menu:antispam:{chat_id}"),
                InlineKeyboardButton("⚖️惩罚策略", callback_data=f"adm:menu:punish:{chat_id}"),
                InlineKeyboardButton("🧹删除提示", callback_data=f"adm:menu:autodel:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🧨关群设置", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton("🕵️改名监控", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton("🌙夜间模式", callback_data=f"adm:menu:night:{chat_id}"),
            ],
            [
                InlineKeyboardButton("💥炸号继承", callback_data=f"adm:menu:inherit:{chat_id}"),
                InlineKeyboardButton("🛡️联盟功能", callback_data=f"adm:menu:alliance:{chat_id}"),
                InlineKeyboardButton("📣强制关注", callback_data=f"adm:menu:forcesub:{chat_id}"),
            ],
            [
                InlineKeyboardButton("⌨️命令配置", callback_data=f"adm:menu:gcmd:{chat_id}"),
                InlineKeyboardButton("🩺健康检查", callback_data=f"adm:menu:health:{chat_id}"),
                InlineKeyboardButton("📊群组统计", callback_data=f"adm:menu:stats:{chat_id}"),
            ],
            [
                InlineKeyboardButton("⚡快捷发布", callback_data=f"adm:menu:qpub:{chat_id}"),
                InlineKeyboardButton("📥导入设置", callback_data=f"adm:menu:import:{chat_id}"),
                InlineKeyboardButton("📋克隆", callback_data=f"adm:menu:clone:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔄切换群", callback_data="adm:switch_group"),
                InlineKeyboardButton("💳续费订阅", callback_data=f"adm:menu:renewal:{chat_id}"),
                InlineKeyboardButton("⚙️管理权限", callback_data=f"adm:menu:control:{chat_id}"),
            ],
        ]
        return InlineKeyboardMarkup(buttons)

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
            [InlineKeyboardButton("🧑‍🍼新成员限制", callback_data="adm:menu:newmem")],
            [
                InlineKeyboardButton("💬自动回复", callback_data="adm:menu:autoreply"),
                InlineKeyboardButton("⏰定时消息", callback_data="adm:menu:scheduled"),
            ],
            [
                InlineKeyboardButton("☂️垃圾防护", callback_data="adm:menu:antispam"),
                InlineKeyboardButton("🔇违禁词", callback_data="adm:menu:keywords"),
            ],
            [InlineKeyboardButton("⚖️惩罚策略", callback_data="adm:menu:punish")],
            [
                InlineKeyboardButton("💰积分", callback_data="adm:menu:points"),
                InlineKeyboardButton("📊统计", callback_data="adm:menu:stats"),
            ],
            [
                InlineKeyboardButton("🧩自定义积分", callback_data="adm:menu:custom_points"),
                InlineKeyboardButton("👑积分等级", callback_data="adm:menu:points_level"),
            ],
            [InlineKeyboardButton("🛍积分商城", callback_data="adm:menu:points_mall")],
            [
                InlineKeyboardButton("🖐联盟功能", callback_data="adm:menu:alliance"),
                InlineKeyboardButton("📡频道同步", callback_data="adm:menu:sync"),
            ],
            [
                InlineKeyboardButton("🚗车库认证", callback_data="adm:menu:garage_auth"),
                InlineKeyboardButton("🔎老师搜索", callback_data="adm:menu:teacher_search"),
            ],
            [InlineKeyboardButton("💯车评系统", callback_data="adm:menu:car_review")],
            [InlineKeyboardButton("🌙夜间模式", callback_data="adm:menu:night")],
            [InlineKeyboardButton("⌨️命令配置", callback_data="adm:menu:gcmd")],
            [InlineKeyboardButton("📥导入设置", callback_data="adm:menu:import")],
            [InlineKeyboardButton("📋克隆", callback_data="adm:menu:clone")],
            [InlineKeyboardButton("⚙️群设置", callback_data="adm:menu:settings")],
        ]
    )


def back_button(to_menu: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{to_menu}")]])


def toggle_menu(rows: list[tuple[str, str, bool]], back_to: str) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"{'✅' if enabled else '❌'} {label}", callback_data=f"adm:toggle:{key}")] for label, key, enabled in rows]
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{back_to}")])
    return InlineKeyboardMarkup(keyboard)
