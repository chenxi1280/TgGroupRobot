from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import ensure_callback_update, resolve_auto_reply_target_chat_id
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.state_service import set_user_state
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.user_service import ensure_user
from sqlalchemy import select

CREATE_AUTO_REPLY_PROMPT = """💬 创建自动回复规则  ( /cancel 取消)

请按以下格式发送配置：

```
关键词1,关键词2,关键词3
匹配类型: contains
区分大小写: false
停止继续匹配: true
删除来源: false
延迟删除: 0
回复内容:
这是自动回复的内容
可以多行
```

匹配类型选项:
• exact - 精确匹配
• contains - 包含匹配（默认）
• starts_with - 以...开头
• ends_with - 以...结尾
• regex - 正则表达式

示例:
```
你好,hi,hello
匹配类型: contains
区分大小写: false
停止继续匹配: true
删除来源: false
延迟删除: 0
回复内容:
你好呀！欢迎来到我们的群组！
```"""


async def auto_reply_create_start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ensure_callback_update(update):
        return
    query = update.callback_query
    await query.answer()

    chat = update.effective_chat
    user = update.effective_user
    target_chat_id = await resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat_title = await _load_target_chat_title(session, chat.type, chat.title, target_chat_id)
        await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        state_chat_id = chat.id if chat.type == "private" else target_chat_id
        await set_user_state(
            session,
            chat_id=state_chat_id,
            user_id=user.id,
            state_type=ConversationStateType.auto_reply_create.value,
            state_data={"step": "config", "target_chat_id": target_chat_id},
        )
        await session.commit()

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"autoreply:cancel:{target_chat_id}")]]
    )
    await query.edit_message_text(CREATE_AUTO_REPLY_PROMPT, parse_mode="Markdown", reply_markup=keyboard)


async def _load_target_chat_title(session, chat_type: str, chat_title: str | None, target_chat_id: int) -> str:
    if chat_type != "private":
        return chat_title or f"群组{target_chat_id}"

    chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
    chat_result = await session.execute(chat_stmt)
    target_chat = chat_result.scalar_one_or_none()
    return target_chat.title if target_chat else f"群组{target_chat_id}"
