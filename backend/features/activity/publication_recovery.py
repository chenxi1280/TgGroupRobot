from __future__ import annotations

import datetime as dt
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.platform.db.schema.models.activity_publications import ActivityPublication
from backend.platform.db.schema.models.expansion import AuctionItem, GuessEvent
from backend.shared.services.permission_service import PermissionPolicyService
from backend.features.activity.services.activity_publication_service import associate_publication_entity

VERIFY_ARGUMENT_COUNT = 2


async def verify_publication_command(update, context):
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if message is None or user is None or chat is None:
        return
    args = await _verification_request(update, context)
    if args is None:
        return
    original = message.reply_to_message
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        record = (await session.execute(select(ActivityPublication).where(
            ActivityPublication.token == args[1], ActivityPublication.chat_id == chat.id,
        ).with_for_update())).scalar_one_or_none()
        await _verify_record(session, record, original, message=message)


async def _verify_record(session, record, original, *, message):
    if record is None or (original.text or original.caption or "") != record.payload.get("text"):
        await message.reply_text("发布编号与原消息内容不匹配，请核对。")
        return
    if record.status == "succeeded":
        await message.reply_text(f"已关联消息 #{record.message_id}，无需重复核实。")
        return
    if record.status not in {"processing", "uncertain"}:
        await message.reply_text("此记录不处于待核实状态。")
        return
    record.status, record.message_id, record.error = "succeeded", original.message_id, None
    record.updated_at = dt.datetime.now(dt.UTC)
    await associate_publication_entity(session, record, original.message_id)
    await session.commit()
    await message.reply_text("已核实并关联原消息；截止时间保持不变。")


async def _verification_request(update, context):
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    args = (message.text or "").split()
    if len(args) != VERIFY_ARGUMENT_COUNT or chat.type == "private" or message.reply_to_message is None:
        await message.reply_text("请在原业务群回复机器人发布的活动消息，发送 /verifypublication 发布编号。")
        return
    allowed, reason = await PermissionPolicyService.require_manage(context, chat.id, user.id)
    if not allowed:
        await message.reply_text(reason or "没有管理权限")
        return
    original = message.reply_to_message
    if original.from_user is None or original.from_user.id != context.bot.id:
        await message.reply_text("只能核实当前机器人在本群发送的原活动消息。")
        return
    return args
