from __future__ import annotations


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.activity.solitaire_shared import WAIT_CONFIG
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import set_user_state
from backend.shared.chat_context import PrivateChatContext
from backend.shared.time_helper import LOCAL_TIMEZONE
from backend.shared.time_ui import next_top_of_hour


async def solitaire_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=2,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
    if target_chat_id is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    from backend.features.activity.date_picker import attach
    data = attach({"target_chat_id": target_chat_id}, back=f"adm:menu:solitaire:{target_chat_id}")
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, state_type="solitaire_create", state_data=data)
        await session.commit()

    await show_solitaire_config_prompt(update, data)
    return WAIT_CONFIG


async def show_solitaire_config_prompt(update, data):
    from backend.features.activity.date_picker import with_calendar
    target_chat_id = data["target_chat_id"]
    deadline_example = next_top_of_hour(days_offset=1).astimezone(LOCAL_TIMEZONE)
    deadline_text = deadline_example.strftime('%Y-%m-%d %H:%M')
    text = (
        "➕ 创建接龙 ( /cancel 取消)\n\n"
        "请按以下格式一次性发送配置：\n\n"
        "```\n"
        "接龙标题\n"
        "描述（可选，可直接留空）\n"
        "最大人数: 0（0=无限制）\n"
        "参与积分: 0（0=无限制）\n"
        "截止时间: YYYY-MM-DD HH:MM（可选，可直接留空）\n"
        "```\n\n"
        "完整示例：\n"
        "```\n"
        "今晚聚餐\n"
        "一起吃火锅\n"
        "最大人数: 10\n"
        "参与积分: 50\n"
        f"截止时间: {deadline_text}\n"
        "```"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"📋 复制 {deadline_text}", api_kwargs={"copy_text": {"text": deadline_text}})],
            [InlineKeyboardButton("🔙 返回上级", callback_data=f"adm:menu:solitaire:{target_chat_id}")],
            [InlineKeyboardButton("❌ 取消配置", callback_data=f"solitaire:cancel:{target_chat_id}")],
        ]
    )
    if data.get("calendar_deadline"):
        text += f"\n日历暂存截止时间：{data['calendar_deadline']}\n配置省略截止时间行时使用该值；填写该行则以配置为准，留空该行可清除。"
    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=with_calendar(keyboard, data))
