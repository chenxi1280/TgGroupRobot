from __future__ import annotations

import datetime as dt
import secrets
from backend.features.activity.services.activity_publication_service import prepare_publication, send_publication, validate_publication_payload, publication_payload
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
    from backend.features.activity.auction_permissions import can_create_auction
    if not await can_create_auction(context, setting, chat_id=chat_id, user_id=user_id):
        await _reply(update, "❌ 拍卖功能未开启或当前创建权限不允许，请联系管理员。")
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
        "本步请发送要拍卖的物品消息，支持纯文字、图片或带说明的图片。\n"
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
    if await _auction_item_input_rejected(flow, data):
        return True
    if not flow.text:
        return await _auction_title_without_text(flow, data)
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
        "cover_file_id": data.get("cover_file_id") or (flow.message.photo[-1].file_id if getattr(flow.message, "photo", None) else None),
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
    from backend.features.activity.date_picker import attach
    next_data = attach({**data, "start_price": amount}, back="auction:date:input")
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
        reply_markup=build_copy_time_keyboard(None, sample_text, picker=next_data.get("__datetime_picker__")),
    )
    return True


async def _handle_auction_end_at(flow: _AuctionFlow, data: dict) -> bool:
    try:
        end_at = parse_auction_end_at(flow.text)
    except ValidationError as exc:
        await _reply(flow.update, f"❌ {exc}")
        return True
    from backend.features.activity.date_picker import clean
    next_data = {**clean(data), "end_at": end_at.isoformat(), "publication_token": data.get("publication_token") or secrets.token_hex(12)}
    await set_user_state(
        flow.session,
        flow.chat.id,
        flow.user.id,
        state_type=ConversationStateType.auction_wait_confirm.value,
        state_data=next_data,
    )
    await flow.session.commit()
    from backend.platform.db.schema.models.expansion import AuctionItem
    preview = AuctionItem(id=0, title=next_data["title"], start_price=next_data["start_price"],
        current_price=next_data["start_price"], end_at=end_at, status="running")
    payload = publication_payload(next_data["publication_token"], {"text": format_auction_announcement(preview), "photo": next_data.get("cover_file_id")})
    try:
        if payload["photo"]:
            await flow.context.bot.send_photo(chat_id=flow.user.id, photo=payload["photo"], caption=payload["text"], parse_mode=None)
        else:
            await flow.context.bot.send_message(chat_id=flow.user.id, text=payload["text"], parse_mode=None)
    except TelegramError:
        await _reply(flow.update, "无法私发预览，请先私聊机器人发送 /start，再发送截止时间重新预览。")
        await set_user_state(flow.session, flow.chat.id, flow.user.id,
            state_type=ConversationStateType.auction_wait_end_at.value, state_data=data)
        await flow.session.commit()
        return True
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
    if not await _check_auction_create_allowed(flow.update, flow.context, flow.setting,
        chat_id=flow.chat.id, user_id=flow.user.id):
        return
    end_at = dt.datetime.fromisoformat(data["end_at"])
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=dt.UTC)
    token = data.get("publication_token")
    if not token:
        await set_user_state(flow.session, flow.chat.id, flow.user.id,
            state_type=ConversationStateType.auction_wait_end_at.value, state_data=data)
        await flow.session.commit()
        await _reply(flow.update, "请重新填写截止时间后确认发布。")
        return
    async def create_entity():
        if end_at <= dt.datetime.now(dt.UTC):
            raise ValidationError("截止时间已过，请修改后发布。")
        item = await publish_auction(flow.session, chat_id=flow.chat.id, creator_user_id=flow.user.id,
            source_message_id=int(data["source_message_id"]), title=str(data["title"]),
            start_price=int(data["start_price"]), end_at=end_at)
        item.cover_file_id = data.get("cover_file_id")
        return item
    record = await prepare_publication(flow.session, token=token, domain="auction", chat_id=flow.chat.id,
        creator_user_id=flow.user.id, create_entity=create_entity,
        render=lambda item: validate_publication_payload({"text": format_auction_announcement(item), "reply_to_message_id": item.source_message_id, "photo": data.get("cover_file_id")}))
    record = await send_publication(flow.session, flow.context, record)
    if record.status != "succeeded":
        await _reply(flow.update, f"拍卖 #{record.entity_id}：{record.error or '发布结果待核实，请勿重复创建'}\n回复原消息发送 /verifypublication {record.token}", parse_mode=None)
        return
    from backend.platform.db.schema.models.expansion import AuctionItem
    item = await flow.session.get(AuctionItem, record.entity_id)
    await _pin_auction_announcement(flow, item, record.message_id)
    await clear_user_state(flow.session, flow.chat.id, flow.user.id)
    await flow.session.commit()


async def _handle_auction_confirm(flow: _AuctionFlow, data: dict) -> bool:
    if flow.text in {"取消", "取消创建"}:
        from backend.platform.state.edit_drafts import suspend_inputs
        await suspend_inputs(flow.session, flow.user.id)
        await flow.session.commit()
        await _reply(flow.update, "已退出拍卖创建，草稿已保留，可从管理首页的草稿入口恢复。")
        return True
    if flow.text not in {"确认", "确认发布", "发布"}:
        await _reply(flow.update, "❌ 请发送 `确认` 发布，或发送 `取消` 退出。")
        return True
    await _publish_auction_from_state(flow, data)
    return True


async def _handle_auction_state(flow: _AuctionFlow, state) -> bool:
    from backend.features.activity.date_picker import block_text
    if await block_text(flow.update, state):
        return True
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
    if reply_message and getattr(reply_message, "photo", None):
        state_data["cover_file_id"] = reply_message.photo[-1].file_id
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


async def _auction_title_without_text(flow, data):
    if data.get("awaiting_item") and getattr(flow.message, "photo", None):
        next_data = {**data, "source_message_id": flow.message.message_id, "cover_file_id": flow.message.photo[-1].file_id}
        next_data.pop("awaiting_item", None)
        await set_user_state(
            flow.session, flow.chat.id, flow.user.id,
            state_type=ConversationStateType.auction_wait_title.value,
            state_data=next_data,
        )
        await flow.session.commit()
        await _reply(flow.update, _auction_title_prompt())
    else:
        await _reply(flow.update, "请输入拍卖标题，已上传的物品消息会保留。")
    return True


async def _auction_item_input_rejected(flow, data):
    if any(getattr(flow.message, field, None) for field in ("video", "document", "audio", "voice", "sticker", "animation")):
        await _reply(flow.update, "本步仅支持文字或按图片方式上传的照片；其他类型暂不支持，草稿已保留。")
        return True
    if data.get("awaiting_item") and _is_auction_create_trigger(flow.text):
        await _reply(flow.update, _auction_item_prompt())
        return True
    if data.get("awaiting_item") and not (flow.text or getattr(flow.message, "photo", None)):
        await _reply(flow.update, "本步支持文字或图片，请重新发送；已填写内容会保留。")
        return True
    return False
