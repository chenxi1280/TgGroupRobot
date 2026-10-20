from __future__ import annotations

from backend.shared.ui.admin_keyboard import admin_keyboard
from backend.shared.ui.menu_layout import navigation_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def create_group_selection_keyboard(
    managed_chats: list[tuple[int, str, bool]],
    current_chat_id: int | None,
    page: int = 0,
) -> InlineKeyboardMarkup:
    page = max(0, min(page, max(0, (len(managed_chats) - 1) // 8)))
    buttons = [
        [InlineKeyboardButton(f"{'✅ ' if chat_id == current_chat_id else ''}{title[:22]} · {chat_id}", callback_data=f"adm:select_group:{chat_id}")]
        for chat_id, title, _ in managed_chats[page * 8:(page + 1) * 8]
    ]
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton("上一页", callback_data=f"adm:switch_group:{page - 1}"))
    if (page + 1) * 8 < len(managed_chats):
        navigation.append(InlineKeyboardButton("下一页", callback_data=f"adm:switch_group:{page + 1}"))
    if navigation:
        buttons.append(navigation)
    if current_chat_id is not None:
        buttons.append(navigation_row(f"adm:menu:main:{current_chat_id}", refresh=f"adm:switch_group:{page}"))
    else:
        buttons.append([InlineKeyboardButton("刷新", callback_data=f"adm:switch_group:{page}")])
    return InlineKeyboardMarkup(buttons)


def create_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{bot_username}")]])


from backend.features.admin.feature_registry import ADMIN_CATEGORIES


def admin_category_menu(category: str, chat_id: int) -> InlineKeyboardMarkup:
    _, features = ADMIN_CATEGORIES[category]
    buttons = [InlineKeyboardButton(label, callback_data=f"adm:menu:{feature}:{chat_id}:category")
               for label, feature in features]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("返回管理首页", callback_data=f"adm:menu:main:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def admin_main_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is None:
        return InlineKeyboardMarkup([[InlineKeyboardButton("选择管理群", callback_data="adm:switch_group")]])
    buttons = [InlineKeyboardButton(title, callback_data=f"adm:menu:category_{key}:{chat_id}")
               for key, (title, _) in ADMIN_CATEGORIES.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    quick = [
        InlineKeyboardButton("自动回复", callback_data=f"adm:menu:autoreply:{chat_id}:home"),
        InlineKeyboardButton("定时消息", callback_data=f"adm:menu:scheduled:{chat_id}:home"),
        InlineKeyboardButton("轮播广告", callback_data=f"adm:menu:ads:{chat_id}:home"),
        InlineKeyboardButton("主积分", callback_data=f"adm:menu:points:{chat_id}:home"),
    ]
    rows = [quick[:2], quick[2:], *rows]
    rows.append([InlineKeyboardButton("继续编辑草稿", callback_data=f"draft:list:{chat_id}:0")])
    rows.append([
        InlineKeyboardButton("切换群", callback_data="adm:switch_group"),
        InlineKeyboardButton("刷新页面", callback_data=f"adm:menu:main:{chat_id}"),
    ])
    return InlineKeyboardMarkup(rows)


def toggle_menu(rows: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"{'✅' if enabled else '❌'} {label}", callback_data=f"adm:toggle:{key}")] for label, key, enabled in rows]
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
    return admin_keyboard(keyboard)
