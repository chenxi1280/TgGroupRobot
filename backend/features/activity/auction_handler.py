from __future__ import annotations

import datetime as dt
import structlog
from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.features.activity.services.auction_service import (
    format_auction_announcement,
    get_or_create_setting,
    get_running_auction_by_reply_message,
    latest_bidder_name,
    parse_auction_end_at,
    parse_bid_amount,
    place_bid,
    publish_auction,
    refresh_auction_message,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import is_user_admin
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.time_ui import build_copy_options_keyboard, build_minutes_or_hhmm_prompt_text, next_top_of_hour_hhmm


log = structlog.get_logger(__name__)


def _is_auction_create_trigger(text: str) -> bool:
    normalized = "".join(
        char
        for char in text
        if not char.isspace() and char not in {"\u200b", "\u200c", "\u200d", "\ufeff"}
    )
    if normalized.startswith("💰"):
        normalized = normalized[1:]
    return normalized == "拍卖"


async def _reply(update: Update, text: str, *, parse_mode: str = "Markdown", reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def auction_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat.type == "private":
        return False

    text = (message.text or message.caption or "").strip()
    if not text:
        return False

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat.id)
        state = await get_user_state(session, chat.id, user.id)

        if state is not None and state.state_type.startswith("auction_wait_"):
            data = dict(state.state_data or {})
            if state.state_type == ConversationStateType.auction_wait_title.value:
                data["title"] = text[:255]
                await set_user_state(
                    session,
                    chat.id,
                    user.id,
                    ConversationStateType.auction_wait_start_price.value,
                    data,
                )
                await session.commit()
                await _reply(update, "💰 请输入起拍价（正整数）：")
                return True

            if state.state_type == ConversationStateType.auction_wait_start_price.value:
                amount = parse_bid_amount(text)
                if amount is None or amount <= 0:
                    await _reply(update, "❌ 起拍价必须是正整数。")
                    return True
                data["start_price"] = amount
                await set_user_state(
                    session,
                    chat.id,
                    user.id,
                    ConversationStateType.auction_wait_end_at.value,
                    data,
                )
                await session.commit()
                hhmm_sample = next_top_of_hour_hhmm(hours_offset=1)
                await _reply(
                    update,
                    build_minutes_or_hhmm_prompt_text(
                        title="💰 拍卖 | 截止时间",
                        minutes_sample_text="30",
                        hhmm_sample_text=hhmm_sample,
                        input_hint="👉 请输入分钟数或 HH:MM：",
                    ),
                    parse_mode="HTML",
                    reply_markup=build_copy_options_keyboard(
                        back_callback=None,
                        options=[("📋 复制 30分钟", "30"), (f"📋 复制 {hhmm_sample}", hhmm_sample)],
                    ),
                )
                return True

            if state.state_type == ConversationStateType.auction_wait_end_at.value:
                try:
                    end_at = parse_auction_end_at(text)
                except ValidationError as exc:
                    await _reply(update, f"❌ {exc}")
                    return True
                data["end_at"] = end_at.isoformat()
                await set_user_state(
                    session,
                    chat.id,
                    user.id,
                    ConversationStateType.auction_wait_confirm.value,
                    data,
                )
                await session.commit()
                summary = "\n".join(
                    [
                        "💰 请确认拍卖信息：",
                        f"标题：{data.get('title')}",
                        f"起拍价：{data.get('start_price')}",
                        f"截止时间：{text}",
                        "",
                        "发送 `确认` 发布，发送 `取消` 放弃。",
                    ]
                )
                await _reply(update, summary)
                return True

            if state.state_type == ConversationStateType.auction_wait_confirm.value:
                if text not in {"确认", "确认发布", "发布"}:
                    if text in {"取消", "取消创建"}:
                        await clear_user_state(session, chat.id, user.id)
                        await session.commit()
                        await _reply(update, "🧹 已取消拍卖创建。")
                        return True
                    await _reply(update, "❌ 请发送 `确认` 发布，或发送 `取消` 退出。")
                    return True
                end_at = dt.datetime.fromisoformat(data["end_at"])
                if end_at.tzinfo is None:
                    end_at = end_at.replace(tzinfo=dt.UTC)
                item = await publish_auction(
                    session,
                    chat_id=chat.id,
                    creator_user_id=user.id,
                    source_message_id=int(data["source_message_id"]),
                    title=str(data["title"]),
                    start_price=int(data["start_price"]),
                    end_at=end_at,
                )
                sent = await context.bot.send_message(
                    chat_id=chat.id,
                    reply_to_message_id=item.source_message_id,
                    text=format_auction_announcement(item),
                    parse_mode="Markdown",
                )
                item.last_announce_message_id = sent.message_id
                if setting.pin_message_enabled:
                    try:
                        await context.bot.pin_chat_message(chat.id, sent.message_id, disable_notification=True)
                    except TelegramError:
                        pass
                await clear_user_state(session, chat.id, user.id)
                await session.commit()
                return True

        is_create_trigger = _is_auction_create_trigger(text)

        if is_create_trigger and message.reply_to_message is None:
            await _reply(update, "💰 请先回复要拍卖的消息，再发送 `拍卖` 进入创建流程。")
            return True

        if message.reply_to_message is not None and is_create_trigger:
            if not setting.enabled:
                await _reply(update, "❌ 拍卖功能未开启，请先在后台开启后再创建。")
                return True
            if setting.create_permission == "admin" and not await is_user_admin(context, chat.id, user.id):
                await _reply(update, "❌ 当前仅管理员可以创建拍卖。")
                return True
            await set_user_state(
                session,
                chat.id,
                user.id,
                ConversationStateType.auction_wait_title.value,
                {"source_message_id": message.reply_to_message.message_id},
            )
            await session.commit()
            await _reply(update, "💰 请输入拍卖标题：")
            return True

        if message.reply_to_message is not None:
            amount = parse_bid_amount(text)
            if amount is None:
                return False
            item = await get_running_auction_by_reply_message(
                session,
                chat_id=chat.id,
                reply_message_id=message.reply_to_message.message_id,
            )
            if item is None:
                return False
            try:
                item, _ = await place_bid(
                    session,
                    chat_id=chat.id,
                    auction_id=item.id,
                    user_id=user.id,
                    amount=amount,
                )
            except ValidationError as exc:
                await session.commit()
                await _reply(update, f"❌ {exc}")
                return True
            bidder_name = await latest_bidder_name(session, item.id)
            await session.commit()
            await _reply(update, f"✅ 出价成功，当前最高价 {item.current_price}。")
            try:
                await refresh_auction_message(context, chat_id=chat.id, item=item, bidder_name=bidder_name)
            except TelegramError:
                log.warning("auction_refresh_failed", chat_id=chat.id, auction_id=item.id)
            return True

    return False
