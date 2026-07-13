from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
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
from backend.platform.state.state_service import (
    clear_user_state,
    get_user_state,
    set_user_state,
)
from backend.shared.time_helper import LOCAL_TIMEZONE
from backend.shared.time_ui import (
    build_copy_time_keyboard,
    build_datetime_prompt_text,
    next_top_of_hour,
)


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


async def _check_auction_create_allowed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    setting,
    *,
    chat_id: int,
    user_id: int,
) -> bool:
    del context, chat_id, user_id
    if not setting.enabled:
        await _reply(update, "❌ 拍卖功能未开启，请联系管理员开启后再创建。")
        return False
    return True


async def _reply(
    update: Update,
    text: str,
    *,
    parse_mode: str = "Markdown",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup
        )


def _auction_item_prompt() -> str:
    return (
        "💰 拍卖 | 拍卖物品\n\n"
        "本步请发送要拍卖的物品消息，可以是文字、图片或其它消息。\n"
        "格式：直接发送物品内容，或回复物品消息发送“拍卖”。\n"
        "完整示例：苹果手机 15 Pro 256G"
    )


def _auction_title_prompt() -> str:
    return (
        "💰 拍卖 | 拍卖标题\n\n"
        "本步只输入拍卖标题，不要带起拍价和截止时间。\n"
        "格式：拍卖标题\n"
        "完整示例：苹果手机 15 Pro 256G"
    )


def _auction_start_price_prompt() -> str:
    return (
        "💰 拍卖 | 起拍价\n\n"
        "本步只输入起拍价，不要带单位。\n"
        "格式：正整数\n"
        "完整示例：100"
    )


def _auction_confirm_prompt(data: dict, deadline_text: str) -> str:
    return "\n".join(
        [
            "💰 请确认拍卖信息：",
            f"标题：{data.get('title')}",
            f"起拍价：{data.get('start_price')}",
            f"截止时间：{deadline_text}",
            "",
            "本步只发送确认指令。",
            "格式：确认 或 取消",
            "完整示例：确认",
        ]
    )


@dataclass(frozen=True)
class _AuctionFlow:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    setting: object
    chat: object
    user: object
    message: object
    text: str


async def _handle_auction_title(flow: _AuctionFlow, data: dict) -> bool:
    if data.get("awaiting_item") and _is_auction_create_trigger(flow.text):
        await _reply(flow.update, _auction_item_prompt())
        return True
    source_message_id = data.get("source_message_id") or getattr(
        flow.message, "message_id", None
    )
    if source_message_id is None:
        await _reply(
            flow.update, "❌ 未能读取拍卖物品消息，请重新发送 `拍卖` 后再回复拍卖物品。"
        )
        return True
    next_data = {
        **data,
        "source_message_id": int(source_message_id),
        "title": flow.text[:255],
    }
    next_data.pop("awaiting_item", None)
    await set_user_state(
        flow.session,
        flow.chat.id,
        flow.user.id,
        state_type=ConversationStateType.auction_wait_start_price.value,
        state_data=next_data,
    )
    await flow.session.commit()
    await _reply(flow.update, _auction_start_price_prompt())
    return True


async def _handle_auction_start_price(flow: _AuctionFlow, data: dict) -> bool:
    amount = parse_bid_amount(flow.text)
    if amount is None or amount <= 0:
        await _reply(flow.update, "❌ 起拍价必须是正整数。")
        return True
    next_data = {**data, "start_price": amount}
    await set_user_state(
        flow.session,
        flow.chat.id,
        flow.user.id,
        state_type=ConversationStateType.auction_wait_end_at.value,
        state_data=next_data,
    )
    await flow.session.commit()
    sample_dt = next_top_of_hour(days_offset=1)
    sample_text = sample_dt.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    prompt = build_datetime_prompt_text(
        title="💰 拍卖 | 截止时间",
        sample_time_text=sample_text,
        sample_time_unix=int(sample_dt.timestamp()),
        input_hint="👉 请输入截止时间：",
        extra_tips=["本步只输入截止时间。"],
    )
    await _reply(
        flow.update,
        prompt,
        parse_mode="HTML",
        reply_markup=build_copy_time_keyboard(None, sample_text),
    )
    return True


async def _handle_auction_end_at(flow: _AuctionFlow, data: dict) -> bool:
    try:
        end_at = parse_auction_end_at(flow.text)
    except ValidationError as exc:
        await _reply(flow.update, f"❌ {exc}")
        return True
    next_data = {**data, "end_at": end_at.isoformat()}
    await set_user_state(
        flow.session,
        flow.chat.id,
        flow.user.id,
        state_type=ConversationStateType.auction_wait_confirm.value,
        state_data=next_data,
    )
    await flow.session.commit()
    await _reply(flow.update, _auction_confirm_prompt(next_data, flow.text))
    return True


async def _pin_auction_announcement(flow: _AuctionFlow, item, message_id: int) -> None:
    if not flow.setting.pin_message_enabled:
        return
    try:
        await flow.context.bot.pin_chat_message(
            flow.chat.id, message_id, disable_notification=True
        )
    except TelegramError as exc:
        log.warning(
            "auction_pin_message_failed",
            chat_id=flow.chat.id,
            auction_id=item.id,
            message_id=message_id,
            error=str(exc),
        )


async def _publish_auction_from_state(flow: _AuctionFlow, data: dict) -> None:
    end_at = dt.datetime.fromisoformat(data["end_at"])
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=dt.UTC)
    item = await publish_auction(
        flow.session,
        chat_id=flow.chat.id,
        creator_user_id=flow.user.id,
        source_message_id=int(data["source_message_id"]),
        title=str(data["title"]),
        start_price=int(data["start_price"]),
        end_at=end_at,
    )
    sent = await flow.context.bot.send_message(
        chat_id=flow.chat.id,
        reply_to_message_id=item.source_message_id,
        text=format_auction_announcement(item),
        parse_mode="Markdown",
    )
    item.last_announce_message_id = sent.message_id
    await _pin_auction_announcement(flow, item, sent.message_id)
    await clear_user_state(flow.session, flow.chat.id, flow.user.id)
    await flow.session.commit()


async def _handle_auction_confirm(flow: _AuctionFlow, data: dict) -> bool:
    if flow.text in {"取消", "取消创建"}:
        await clear_user_state(flow.session, flow.chat.id, flow.user.id)
        await flow.session.commit()
        await _reply(flow.update, "🧹 已取消拍卖创建。")
        return True
    if flow.text not in {"确认", "确认发布", "发布"}:
        await _reply(flow.update, "❌ 请发送 `确认` 发布，或发送 `取消` 退出。")
        return True
    await _publish_auction_from_state(flow, data)
    return True


async def _handle_auction_state(flow: _AuctionFlow, state) -> bool:
    handlers = {
        ConversationStateType.auction_wait_title.value: _handle_auction_title,
        ConversationStateType.auction_wait_start_price.value: _handle_auction_start_price,
        ConversationStateType.auction_wait_end_at.value: _handle_auction_end_at,
        ConversationStateType.auction_wait_confirm.value: _handle_auction_confirm,
    }
    handler = handlers.get(state.state_type)
    if handler is None:
        return False
    return await handler(flow, dict(state.state_data or {}))


async def _start_auction_creation(flow: _AuctionFlow) -> bool:
    if not await _check_auction_create_allowed(
        flow.update,
        flow.context,
        flow.setting,
        chat_id=flow.chat.id,
        user_id=flow.user.id,
    ):
        return True
    reply_message = flow.message.reply_to_message
    state_data = (
        {"source_message_id": reply_message.message_id}
        if reply_message
        else {"awaiting_item": True}
    )
    await set_user_state(
        flow.session,
        flow.chat.id,
        flow.user.id,
        state_type=ConversationStateType.auction_wait_title.value,
        state_data=state_data,
    )
    await flow.session.commit()
    await _reply(
        flow.update,
        _auction_title_prompt() if reply_message else _auction_item_prompt(),
    )
    return True


async def _handle_auction_bid(flow: _AuctionFlow) -> bool:
    reply_message = flow.message.reply_to_message
    if reply_message is None:
        return False
    amount = parse_bid_amount(flow.text)
    if amount is None:
        return False
    item = await get_running_auction_by_reply_message(
        flow.session,
        chat_id=flow.chat.id,
        reply_message_id=reply_message.message_id,
    )
    if item is None:
        return False
    try:
        item, _ = await place_bid(
            flow.session,
            chat_id=flow.chat.id,
            auction_id=item.id,
            user_id=flow.user.id,
            amount=amount,
        )
    except ValidationError as exc:
        await flow.session.commit()
        await _reply(flow.update, f"❌ {exc}")
        return True
    bidder_name = await latest_bidder_name(flow.session, item.id)
    await flow.session.commit()
    await _reply(flow.update, f"✅ 出价成功，当前最高价 {item.current_price}。")
    try:
        await refresh_auction_message(
            flow.context, chat_id=flow.chat.id, item=item, bidder_name=bidder_name
        )
    except TelegramError:
        log.warning("auction_refresh_failed", chat_id=flow.chat.id, auction_id=item.id)
    return True


def _auction_message_parts(update: Update):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat is None or user is None or message is None or chat.type == "private":
        return None
    text = (message.text or message.caption or "").strip()
    if not text:
        return None
    return chat, user, message, text


async def auction_group_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    parts = _auction_message_parts(update)
    if parts is None:
        return False
    chat, user, message, text = parts

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat.id)
        state = await get_user_state(session, chat.id, user.id)
        flow = _AuctionFlow(
            update=update,
            context=context,
            session=session,
            setting=setting,
            chat=chat,
            user=user,
            message=message,
            text=text,
        )
        if state is not None and state.state_type.startswith("auction_wait_"):
            if await _handle_auction_state(flow, state):
                return True
        if _is_auction_create_trigger(text):
            return await _start_auction_creation(flow)
        return await _handle_auction_bid(flow)
