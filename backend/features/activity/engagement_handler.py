from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.activity.services.engagement_service import (
    get_or_create_chat_reward,
    increase_message_count,
    try_claim_chat_reward,
    try_claim_egg,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user
from backend.shared.services.publish_service import PublishService


async def engagement_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return False
    if update.effective_chat.type == "private":
        return False

    text = (update.effective_message.text or "").strip()
    if not text:
        return False

    db: Database = context.application.bot_data["db"]
    egg_reward: int | None = None
    chat_reward_result: tuple[int, int] | None = None
    chat_reward_error: str | None = None
    command_keyword: str | None = None

    async with db.session_factory() as session:
        await ensure_user(
            session,
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )
        await increase_message_count(session, update.effective_chat.id, update.effective_user.id)
        reward = await get_or_create_chat_reward(session, update.effective_chat.id)
        command_keyword = reward.command_keyword
        egg_reward = await try_claim_egg(session, update.effective_chat.id, update.effective_user.id, text)
        if text == reward.command_keyword:
            try:
                chat_reward_result = await try_claim_chat_reward(session, update.effective_chat.id, update.effective_user.id)
            except ValidationError as exc:
                chat_reward_error = str(exc)
        await session.commit()

    if egg_reward is not None:
        await PublishService.reply(
            context,
            chat_id=update.effective_chat.id,
            text=f"🥚 恭喜你猜中彩蛋答案！\n🎁 获得奖励：{egg_reward} 积分",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    if chat_reward_result is not None:
        points, streak = chat_reward_result
        await PublishService.reply(
            context,
            chat_id=update.effective_chat.id,
            text=f"💬 水群激励领取成功\n🎁 奖励积分：{points}\n🔥 连续达标：{streak} 天",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    if chat_reward_error and text == command_keyword:
        await PublishService.reply(
            context,
            chat_id=update.effective_chat.id,
            text=f"⚠️ {chat_reward_error}",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    return False
