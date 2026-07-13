from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.auction_settings import get_or_create_setting
from backend.features.activity.services.auction_time import as_utc, now_utc
from backend.features.points.services.points_service import get_balance
from backend.platform.db.schema.models.expansion import AuctionBid, AuctionItem
from backend.shared.services.base import ValidationError
AUTO_EXTEND_THRESHOLD_SECONDS = 60
AUTO_EXTEND_SECONDS = 60



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
    item = _validate_bid_item(result.scalar_one_or_none(), amount)

    setting = await get_or_create_setting(session, chat_id)
    if setting.points_mode == "group_points":
        balance = await get_balance(session, chat_id, user_id)
        if balance < amount:
            raise ValidationError(f"当前主积分不足，余额仅 {balance}。")

    item.current_price = amount
    _extend_auction_if_needed(item, auto_extend_enabled=setting.auto_extend_enabled)

    bid = AuctionBid(
        auction_id=item.id,
        chat_id=chat_id,
        bid_user_id=user_id,
        bid_amount=amount,
    )
    session.add(bid)
    item.updated_at = now_utc()
    await session.flush()
    return item, bid
def _validate_bid_item(item: AuctionItem | None, amount: int) -> AuctionItem:
    if item is None:
        raise ValidationError("拍卖不存在。")
    if item.status != "running":
        raise ValidationError("拍卖已结束，不能继续出价。")
    if item.end_at is None or as_utc(item.end_at) <= now_utc():
        raise ValidationError("拍卖已到截止时间，请等待系统结算。")
    if amount <= item.current_price:
        raise ValidationError("出价必须大于当前价。")
    return item


def _extend_auction_if_needed(item: AuctionItem, *, auto_extend_enabled: bool) -> None:
    if not auto_extend_enabled or item.end_at is None:
        return
    remain_seconds = int((as_utc(item.end_at) - now_utc()).total_seconds())
    if remain_seconds <= AUTO_EXTEND_THRESHOLD_SECONDS:
        item.end_at = as_utc(item.end_at) + dt.timedelta(seconds=AUTO_EXTEND_SECONDS)
