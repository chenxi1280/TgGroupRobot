from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.models.enums import PointsTxnType
from bot.models.expansion import AuctionBid, AuctionItem, AuctionSetting
from bot.services.activity.points_service import change_points, get_balance
from bot.services.base import ValidationError
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.user_service import ensure_user


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def parse_auction_end_at(raw: str, *, now: dt.datetime | None = None) -> dt.datetime:
    value = raw.strip()
    current = _as_utc(now or _now())
    if re.fullmatch(r"\d+", value):
        minutes = int(value)
        if minutes <= 0:
            raise ValidationError("截止时间必须大于 0 分钟。")
        return current + dt.timedelta(minutes=minutes)

    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        hour, minute = map(int, value.split(":"))
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target += dt.timedelta(days=1)
        return target

    raise ValidationError("截止时间格式错误，请输入分钟数或 HH:MM。")


def parse_bid_amount(raw: str) -> int | None:
    text = raw.strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"出价[:： ]*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def format_auction_settings_text(chat_title: str, setting: AuctionSetting) -> str:
    return "\n".join(
        [
            f"💰 拍卖 | {chat_title}",
            "",
            f"⚙️ 状态：{'✅ 启动' if setting.enabled else '❌ 关闭'}",
            f"📌 消息置顶：{'✅ 启动' if setting.pin_message_enabled else '❌ 关闭'}",
            f"⏱ 自动延时：{'✅ 启动' if setting.auto_extend_enabled else '❌ 关闭'}",
            f"👮 创建权限：{'👑 仅管理员' if setting.create_permission == 'admin' else '👥 所有人'}",
            f"🪙 关联积分：{'🌑 主积分' if setting.points_mode == 'group_points' else '🚫 不关联'}",
            "",
            "群内回复任意消息发送“拍卖”即可进入创建流程。",
        ]
    )


def format_auction_announcement(
    item: AuctionItem,
    *,
    bidder_name: str | None = None,
    is_final: bool = False,
    settlement_note: str | None = None,
) -> str:
    status_text = {
        "running": "🟢 进行中",
        "ended": "🔴 已结束",
        "cancelled": "⚫ 已取消",
        "draft": "🟡 草稿",
    }.get(item.status, item.status)
    lines = [
        f"💰 拍卖：{item.title or '未命名拍卖'}",
        "",
        f"状态：{status_text}",
        f"起拍价：{item.start_price}",
        f"当前价：{item.current_price}",
        f"结束时间：{_as_utc(item.end_at or _now()).astimezone().strftime('%Y-%m-%d %H:%M:%S') if item.end_at else '未设置'}",
    ]
    if bidder_name:
        lines.append(f"当前领先：{bidder_name}")
    if is_final:
        lines.append(f"结束时间：{_as_utc(item.updated_at).astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    if settlement_note:
        lines.extend(["", settlement_note])
    else:
        lines.extend(["", "回复本条消息发送数字即可出价，例如：`188`"])
    return "\n".join(lines)


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> AuctionSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(AuctionSetting, chat_id)
    if setting is None:
        setting = AuctionSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> AuctionSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = _now()
    await session.flush()
    return setting


async def publish_auction(
    session: AsyncSession,
    *,
    chat_id: int,
    creator_user_id: int,
    source_message_id: int,
    title: str,
    start_price: int,
    end_at: dt.datetime,
) -> AuctionItem:
    await ModuleSettingsService.ensure(session, chat_id=chat_id, user_id=creator_user_id)
    await ensure_user(session, creator_user_id, None, None, None, None)
    item = AuctionItem(
        chat_id=chat_id,
        creator_user_id=creator_user_id,
        source_message_id=source_message_id,
        title=title.strip(),
        start_price=start_price,
        current_price=start_price,
        status="running",
        start_at=_now(),
        end_at=_as_utc(end_at),
    )
    session.add(item)
    await session.flush()
    return item


async def get_running_auction_by_reply_message(
    session: AsyncSession,
    *,
    chat_id: int,
    reply_message_id: int,
) -> AuctionItem | None:
    stmt = (
        select(AuctionItem)
        .where(
            AuctionItem.chat_id == chat_id,
            AuctionItem.status == "running",
            or_(
                AuctionItem.last_announce_message_id == reply_message_id,
                AuctionItem.source_message_id == reply_message_id,
            ),
        )
        .order_by(desc(AuctionItem.id))
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def place_bid(
    session: AsyncSession,
    *,
    chat_id: int,
    auction_id: int,
    user_id: int,
    amount: int,
) -> tuple[AuctionItem, AuctionBid]:
    stmt = (
        select(AuctionItem)
        .where(and_(AuctionItem.id == auction_id, AuctionItem.chat_id == chat_id))
        .with_for_update()
    )
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise ValidationError("拍卖不存在。")
    if item.status != "running":
        raise ValidationError("拍卖已结束，不能继续出价。")
    if item.end_at is None or _as_utc(item.end_at) <= _now():
        raise ValidationError("拍卖已到截止时间，请等待系统结算。")
    if amount <= item.current_price:
        raise ValidationError("出价必须大于当前价。")

    setting = await get_or_create_setting(session, chat_id)
    if setting.points_mode == "group_points":
        balance = await get_balance(session, chat_id, user_id)
        if balance < amount:
            raise ValidationError(f"当前主积分不足，余额仅 {balance}。")

    item.current_price = amount
    if setting.auto_extend_enabled and item.end_at is not None:
        remain_seconds = int((_as_utc(item.end_at) - _now()).total_seconds())
        if remain_seconds <= 60:
            item.end_at = _as_utc(item.end_at) + dt.timedelta(seconds=60)

    bid = AuctionBid(
        auction_id=item.id,
        chat_id=chat_id,
        bid_user_id=user_id,
        bid_amount=amount,
    )
    session.add(bid)
    item.updated_at = _now()
    await session.flush()
    return item, bid


@dataclass
class AuctionSettlementResult:
    item: AuctionItem
    winner_user_id: int | None
    winning_amount: int
    note: str


async def _resolve_settlement_winner(
    session: AsyncSession,
    *,
    item: AuctionItem,
    points_mode: str,
) -> tuple[AuctionBid | None, str]:
    bid_stmt = (
        select(AuctionBid)
        .where(AuctionBid.auction_id == item.id)
        .order_by(desc(AuctionBid.bid_amount), AuctionBid.created_at.asc())
    )
    bid_result = await session.execute(bid_stmt)
    bids = list(bid_result.scalars().all())
    if not bids:
        return None, "😔 无人出价，本次拍卖流拍。"

    if points_mode != "group_points":
        return bids[0], f"🏆 中标用户：{bids[0].bid_user_id}\n💸 成交价：{bids[0].bid_amount}\n🪙 未启用积分扣费。"

    for bid in bids:
        ok, balance = await change_points(
            session,
            item.chat_id,
            bid.bid_user_id,
            -bid.bid_amount,
            PointsTxnType.penalty.value,
            reason=f"拍卖成交 #{item.id}",
        )
        if ok:
            return bid, f"🏆 中标用户：{bid.bid_user_id}\n💸 成交价：{bid.bid_amount}\n🪙 已扣除主积分，剩余 {balance}。"
    return None, "😔 所有有效出价用户当前积分都不足，拍卖流拍。"


async def settle_due_auctions(session: AsyncSession) -> list[AuctionSettlementResult]:
    now = _now()
    stmt = select(AuctionItem).where(
        AuctionItem.status == "running",
        AuctionItem.end_at.is_not(None),
        AuctionItem.end_at <= now,
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    settlements: list[AuctionSettlementResult] = []
    for item in items:
        item = (await session.execute(
            select(AuctionItem).where(AuctionItem.id == item.id).with_for_update()
        )).scalar_one()
        setting = await get_or_create_setting(session, item.chat_id)
        winner_bid, note = await _resolve_settlement_winner(session, item=item, points_mode=setting.points_mode)
        item.status = "ended"
        item.updated_at = now
        if winner_bid is not None:
            item.winner_user_id = winner_bid.bid_user_id
            item.winner_bid_id = winner_bid.id
            item.current_price = winner_bid.bid_amount
        settlements.append(
            AuctionSettlementResult(
                item=item,
                winner_user_id=item.winner_user_id,
                winning_amount=item.current_price,
                note=note,
            )
        )
    await session.flush()
    return settlements


async def latest_bidder_name(session: AsyncSession, auction_id: int) -> str | None:
    stmt = (
        select(AuctionBid.bid_user_id)
        .where(AuctionBid.auction_id == auction_id)
        .order_by(desc(AuctionBid.bid_amount), AuctionBid.created_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    user_id = result.scalar_one_or_none()
    if user_id is None:
        return None
    return f"用户 {user_id}"


async def list_recent_auctions(session: AsyncSession, chat_id: int, limit: int = 5) -> list[AuctionItem]:
    stmt = (
        select(AuctionItem)
        .where(AuctionItem.chat_id == chat_id)
        .order_by(desc(AuctionItem.id))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_auctions(
    session: AsyncSession,
    chat_id: int,
    *,
    page: int = 0,
    page_size: int = 10,
) -> tuple[list[AuctionItem], int]:
    normalized_page = max(page, 0)
    normalized_page_size = max(page_size, 1)
    count_stmt = select(func.count()).select_from(AuctionItem).where(AuctionItem.chat_id == chat_id)
    total_count = int((await session.execute(count_stmt)).scalar_one() or 0)
    stmt = (
        select(AuctionItem)
        .where(AuctionItem.chat_id == chat_id)
        .order_by(desc(AuctionItem.id))
        .offset(normalized_page * normalized_page_size)
        .limit(normalized_page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total_count


async def get_auction(session: AsyncSession, chat_id: int, auction_id: int) -> AuctionItem | None:
    stmt = select(AuctionItem).where(AuctionItem.chat_id == chat_id, AuctionItem.id == auction_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def refresh_auction_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    item: AuctionItem,
    bidder_name: str | None = None,
    settlement_note: str | None = None,
    parse_mode: str = "Markdown",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if item.last_announce_message_id is None:
        return
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=item.last_announce_message_id,
        text=format_auction_announcement(item, bidder_name=bidder_name, is_final=item.status == "ended", settlement_note=settlement_note),
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
