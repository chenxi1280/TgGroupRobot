from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def create_group_selection_keyboard(
    managed_chats: list[tuple[int, str, bool]],
    current_chat_id: int | None,
    page: int = 0,
) -> InlineKeyboardMarkup:
    page = max(0, min(page, max(0, (len(managed_chats) - 1) // 8)))
    buttons = [
        [InlineKeyboardButton(f"{'✅ ' if chat_id == current_chat_id else ''}{title}", callback_data=f"adm:select_group:{chat_id}")]
        for chat_id, title, _ in managed_chats[page * 8:(page + 1) * 8]
    ]
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton("上一页", callback_data=f"adm:switch_group:{page - 1}"))
    if (page + 1) * 8 < len(managed_chats):
        navigation.append(InlineKeyboardButton("下一页", callback_data=f"adm:switch_group:{page + 1}"))
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton("刷新", callback_data=f"adm:switch_group:{page}")])
    if current_chat_id is not None:
        buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{current_chat_id}")])
    return InlineKeyboardMarkup(buttons)


def create_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{bot_username}")]])


from backend.features.admin.feature_registry import ADMIN_CATEGORIES


def admin_category_menu(category: str, chat_id: int) -> InlineKeyboardMarkup:
    _, features = ADMIN_CATEGORIES[category]
    buttons = [InlineKeyboardButton(label, callback_data=f"adm:menu:{feature}:{chat_id}")
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
    rows.append([
        InlineKeyboardButton("切换群", callback_data="adm:switch_group"),
        InlineKeyboardButton("刷新页面", callback_data=f"adm:menu:main:{chat_id}"),
    ])
    rows.append([InlineKeyboardButton("继续编辑草稿", callback_data=f"draft:list:{chat_id}:0")])
    return InlineKeyboardMarkup(rows)


def toggle_menu(rows: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"{'✅' if enabled else '❌'} {label}", callback_data=f"adm:toggle:{key}")] for label, key, enabled in rows]
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
    return InlineKeyboardMarkup(keyboard)
