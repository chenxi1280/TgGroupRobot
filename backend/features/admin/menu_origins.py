"""Origin-aware navigation scoped by user data, explicit group and stable feature ID."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def remember_menu_origin(context, *, chat_id: int, feature: str, source: str):
    if source in {"home", "category"}:
        context.user_data.setdefault("menu_origins", {})[f"{chat_id}:{feature}"] = source


def with_menu_origin(markup, context, *, chat_id: int, feature: str):
    origin = (getattr(context, "user_data", None) or {}).get("menu_origins", {}).get(f"{chat_id}:{feature}")
    if origin != "home":
        return markup
    rows = []
    for row in markup.inline_keyboard:
        rows.append([InlineKeyboardButton("返回管理首页", callback_data=f"adm:menu:main:{chat_id}")
            if (button.callback_data or "").startswith("adm:menu:category_") else button for button in row])
    return InlineKeyboardMarkup(rows)
