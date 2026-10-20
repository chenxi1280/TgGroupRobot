"""Explicit administrative layout; published betting controls remain separate."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def guess_draft_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏷️ 活动名字", callback_data=f"guess:create:{chat_id}:title"),
            InlineKeyboardButton("🖼️ 活动封面", callback_data=f"guess:create:{chat_id}:cover"),
        ],
        [
            InlineKeyboardButton("📝 活动说明", callback_data=f"guess:create:{chat_id}:description"),
            InlineKeyboardButton("👑 本局庄家", callback_data=f"guess:create:{chat_id}:banker"),
        ],
        [
            InlineKeyboardButton("🏦 公共奖池", callback_data=f"guess:create:{chat_id}:pool"),
            InlineKeyboardButton("🎯 竞猜选项", callback_data=f"guess:create:{chat_id}:options"),
        ],
        [
            InlineKeyboardButton("⌨️ 群内指令", callback_data=f"guess:create:{chat_id}:command"),
            InlineKeyboardButton("⏰ 截止时间", callback_data=f"guess:create:{chat_id}:deadline"),
        ],
        [
            InlineKeyboardButton("下注限制", callback_data=f"guess:create:{chat_id}:repeat"),
        ],
        [
            InlineKeyboardButton("🏖️ 预览效果", callback_data=f"guess:create:{chat_id}:preview"),
            InlineKeyboardButton("✅ 发布活动", callback_data=f"guess:create:{chat_id}:publish"),
        ],
        [
            InlineKeyboardButton("❌ 清空配置", callback_data=f"guess:create:{chat_id}:clear"),
        ],
        [
            InlineKeyboardButton("⬅️ 返回", callback_data=f"guess:home:{chat_id}"),
        ],
    ])
    return keyboard
