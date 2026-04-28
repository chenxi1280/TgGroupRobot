from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
    mark_callback_query_answered,
)
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user
from backend.features.moderation.banned_word_message import safe_edit_banned_word_message
from sqlalchemy import select

log = structlog.get_logger(__name__)

BANNED_WORD_CREATE_PROMPT = """🔇 添加违禁词  ( /cancel 取消)

请按以下格式发送配置：

```
违禁词
匹配类型: 包含
惩罚动作: 删除
禁言时长: 60
删除提醒: 是
提醒消息: 您的消息因包含违禁词被删除
```

匹配类型:
• 精确 - 消息必须完全等于违禁词
• 包含 - 消息里出现这个词就拦截（默认）
• 正则 - 高级规则

惩罚动作:
• 删除 - 删除消息（默认）
• 禁言 - 删除并禁言
• 封禁 - 删除并封禁

示例:
```
垃圾广告
匹配类型: 精确
惩罚动作: 禁言
禁言时长: 300
删除提醒: 是
提醒消息: 请不要发送垃圾广告！
```"""


async def banned_word_add_start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("banned_word_add_start_called", user_id=update.effective_user.id if update.effective_user else None)
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    data = query.data or ""

    try:
        target_chat_id, target_chat_title = await _resolve_banned_word_target(update, context, data)
        if target_chat_id is None:
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
            if chat.type == "private":
                await ensure_chat(session, chat_id=user.id, chat_type="private", title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            await clear_user_state(session, chat_id=target_chat_id, user_id=user.id)
            await set_user_state(
                session,
                chat_id=target_chat_id,
                user_id=user.id,
                state_type=ConversationStateType.banned_word_add.value,
                state_data={"step": "config", "target_chat_id": target_chat_id},
            )
            await session.commit()

    except Exception as exc:
        log.exception("banned_word_add_start_error", error=str(exc))
        await safe_edit_banned_word_message(query, f"❌ 启动失败: {str(exc)}")
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"keywords:cancel:{target_chat_id}")]]
    )
    await query.answer()
    mark_callback_query_answered(update)
    await safe_edit_banned_word_message(
        query,
        BANNED_WORD_CREATE_PROMPT,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _resolve_banned_word_target(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> tuple[int | None, str | None]:
    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]

    if chat.type != "private":
        if not await is_user_admin(context, chat.id, user.id):
            await answer_callback_query_safely(update, "需要管理员权限。", show_alert=True)
            return None, None
        return chat.id, chat.title

    target_chat_id = 0
    if data.startswith("banned_word:add:"):
        target_chat_id = CallbackParser.parse(data).get_int(2)
    if target_chat_id == 0:
        await answer_callback_query_safely(update, "❌ 群组参数无效，请返回重试", show_alert=True)
        return None, None
    if not await is_user_admin(context, target_chat_id, user.id):
        await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
        return None, None

    async with db.session_factory() as session:
        chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
        chat_result = await session.execute(chat_stmt)
        target_chat = chat_result.scalar_one_or_none()
        await session.commit()
    return target_chat_id, target_chat.title if target_chat else f"群组{target_chat_id}"
