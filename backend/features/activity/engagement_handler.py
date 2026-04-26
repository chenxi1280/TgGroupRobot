from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.activity.services.engagement_service import (
    get_or_create_chat_reward,
    increase_message_count,
    try_claim_chat_reward,
    try_claim_egg,
    update_egg_event_from_template,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.services.user_service import ensure_user
from backend.shared.services.publish_service import PublishService
from backend.features.group_ops.text_trigger_runtime import is_reserved_group_text_command_for_chat


def _is_add_egg_command(text: str, bot_username: str | None) -> bool:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line == "添加彩蛋":
        return True
    match = re.fullmatch(r"@(\w+)\s+添加彩蛋", first_line, flags=re.IGNORECASE)
    if not match:
        return False
    if bot_username:
        return match.group(1).lower() == bot_username.lower()
    return True


def _contains_egg_answer_field(text: str) -> bool:
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        if re.match(r"^(?:【\s*答案\s*】|答案\s*[=:：])", line):
            return True
    return False


async def engagement_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return False
    if update.effective_chat.type == "private":
        return False

    text = (update.effective_message.text or "").strip()
    if not text:
        return False
    db: Database = context.application.bot_data["db"]
    if _is_add_egg_command(text, getattr(context.bot, "username", None)):
        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            update.effective_chat.id,
            update.effective_user.id,
            capability="engagement",
        )
        if not allowed:
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text=f"⚠️ {error_text or '需要管理员权限'}，无法添加彩蛋。",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        if _contains_egg_answer_field(text):
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text="⚠️ 彩蛋答案不能在群聊里配置。请到机器人私聊中复制模板并创建，避免群友提前看到答案。",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        try:
            async with db.session_factory() as session:
                await ensure_user(
                    session,
                    user_id=update.effective_user.id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    last_name=update.effective_user.last_name,
                    language_code=update.effective_user.language_code,
                )
                event = await update_egg_event_from_template(session, update.effective_chat.id, text)
                await session.commit()
        except ValidationError as exc:
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text=f"⚠️ 彩蛋创建失败：{exc}",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        await PublishService.reply(
            context,
            chat_id=update.effective_chat.id,
            text=(
                f"✅ 彩蛋已添加：#{event.id} {event.title}\n"
                f"🧩 线索：{len(event.clues or [])} 条\n"
                f"⏰ 发布时间：{' / '.join(event.clue_times or [])}\n"
                "到点会自动发布线索，也可以在促活工具里手动发布。\n"
                "提醒：含答案模板建议在私聊里创建，避免群友提前看到答案。"
            ),
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

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
        reserved_text_command = await is_reserved_group_text_command_for_chat(session, update.effective_chat.id, text)
        command_keyword = reward.command_keyword
        egg_reward = None if reserved_text_command else await try_claim_egg(
            session,
            update.effective_chat.id,
            update.effective_user.id,
            text,
        )
        if not reserved_text_command and text == reward.command_keyword:
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
