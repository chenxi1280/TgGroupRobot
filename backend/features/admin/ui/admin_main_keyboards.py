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


_SCOPED_ADMIN_MENU = (
    (("🎠轮播广告", "adm:menu:ads:{id}"), ("💬自动回复", "adm:menu:autoreply:{id}"), ("⏰定时消息", "sm:list:{id}:0")),
    (("🚗车库认证", "adm:menu:garage_auth:{id}"), ("🔍老师搜索", "adm:menu:teacher_search:{id}"), ("📡频道同步", "adm:menu:sync:{id}")),
    (("🌑主积分", "adm:menu:points:{id}"), ("🌐自定义积分", "adm:menu:custom_points:{id}"), ("🧑‍🎓积分等级", "adm:menu:points_level:{id}")),
    (("🛒积分商城", "adm:menu:points_mall:{id}"), ("💯车评系统", "adm:menu:car_review:{id}"), ("⌨️底部按钮", "adm:menu:bottom_button:{id}")),
    (("💰拍卖", "adm:menu:auction:{id}"), ("🎁抽奖", "adm:menu:lottery:{id}"), ("✨促活工具", "adm:menu:engagement:{id}")),
    (("🎮游戏", "adm:menu:game:{id}"), ("⚽竞猜", "adm:menu:guess:{id}"), ("🔗邀请链接", "adm:menu:invite:{id}")),
    (("🎉进群欢迎", "adm:menu:welcome:{id}"), ("🛡️进群验证", "adm:menu:verification:{id}"), ("🧑‍🍼新成员限制", "adm:menu:newmem:{id}")),
    (("☂️垃圾防护", "adm:menu:antispam:{id}"), ("⚖️惩罚策略", "adm:menu:punish:{id}"), ("🧹删除提示", "adm:menu:autodel:{id}")),
    (("🌙夜间管控", "adm:menu:night:{id}"), ("🕵️改名监控", "adm:menu:renamewatch:{id}"), ("📣强制关注", "adm:menu:forcesub:{id}")),
    (("💥炸号继承", "adm:menu:inherit:{id}"), ("🛡️联盟功能", "adm:menu:alliance:{id}"), ("⌨️命令配置", "adm:menu:gcmd:{id}")),
    (("⚙️群设置", "adm:menu:settings:{id}"), ("🩺健康检查", "adm:menu:health:{id}"), ("📊群组统计", "adm:menu:stats:{id}")),
    (("⚡快捷发布", "adm:menu:qpub:{id}"), ("📥导入设置", "adm:menu:import:{id}"), ("📋克隆", "adm:menu:clone:{id}")),
    (("🔄切换群", "adm:switch_group"), ("💳续费订阅", "adm:menu:renewal:{id}"), ("⚙️管理权限", "adm:menu:control:{id}")),
)

_UNSCOPED_ADMIN_MENU = (
    (("🎁抽奖", "adm:menu:lottery"), ("🔗邀请链接", "adm:menu:invite")),
    (("👋欢迎", "adm:menu:welcome"), ("🤖验证", "adm:menu:verification")),
    (("🧑‍🍼新成员限制", "adm:menu:newmem"),), (("💬自动回复", "adm:menu:autoreply"), ("⏰定时消息", "adm:menu:scheduled")),
    (("☂️垃圾防护", "adm:menu:antispam"), ("🔇违禁词", "adm:menu:keywords")), (("⚖️惩罚策略", "adm:menu:punish"),),
    (("💰积分", "adm:menu:points"), ("📊统计", "adm:menu:stats")), (("🧩自定义积分", "adm:menu:custom_points"), ("👑积分等级", "adm:menu:points_level")),
    (("🛍积分商城", "adm:menu:points_mall"),), (("🖐联盟功能", "adm:menu:alliance"), ("📡频道同步", "adm:menu:sync")),
    (("🚗车库认证", "adm:menu:garage_auth"), ("🔎老师搜索", "adm:menu:teacher_search")), (("💯车评系统", "adm:menu:car_review"),),
    (("🌙夜间管控", "adm:menu:night"),), (("⌨️命令配置", "adm:menu:gcmd"),), (("📥导入设置", "adm:menu:import"),),
    (("📋克隆", "adm:menu:clone"),), (("⚙️群设置", "adm:menu:settings"),),
)


def _menu_markup(definitions, chat_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=callback.format(id=chat_id)) for label, callback in row]
        for row in definitions
    ]
    return InlineKeyboardMarkup(rows)


def admin_main_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    definitions = _SCOPED_ADMIN_MENU if chat_id is not None else _UNSCOPED_ADMIN_MENU
    return _menu_markup(definitions, chat_id)


def back_button(to_menu: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{to_menu}")]])


def toggle_menu(rows: list[tuple[str, str, bool]], back_to: str) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"{'✅' if enabled else '❌'} {label}", callback_data=f"adm:toggle:{key}")] for label, key, enabled in rows]
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{back_to}")])
    return InlineKeyboardMarkup(keyboard)
