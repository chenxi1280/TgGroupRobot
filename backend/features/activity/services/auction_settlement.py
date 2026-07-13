from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.auction_settings import get_or_create_setting
from backend.features.activity.services.auction_time import now_utc
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import AuctionBid, AuctionItem


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
            amount=-bid.bid_amount,
            txn_type=PointsTxnType.penalty.value,
            reason=f"拍卖成交 #{item.id}",
        )
        if ok:
            return bid, f"🏆 中标用户：{bid.bid_user_id}\n💸 成交价：{bid.bid_amount}\n🪙 已扣除主积分，剩余 {balance}。"
    return None, "😔 所有有效出价用户当前积分都不足，拍卖流拍。"


async def settle_due_auctions(session: AsyncSession) -> list[AuctionSettlementResult]:
    item_ids = await list_due_auction_ids(session)
    settlements: list[AuctionSettlementResult] = []
    for item_id in item_ids:
        result = await settle_due_auction(session, item_id)
        if result is not None:
            settlements.append(result)
    await session.flush()
    return settlements


async def list_due_auction_ids(session: AsyncSession) -> list[int]:
    now = now_utc()
    stmt = select(AuctionItem.id).where(
        AuctionItem.status == "running",
        AuctionItem.end_at.is_not(None),
        AuctionItem.end_at <= now,
    )
    result = await session.execute(stmt)
    return [int(item_id) for item_id in result.scalars().all()]


async def settle_due_auction(session: AsyncSession, item_id: int) -> AuctionSettlementResult | None:
    now = now_utc()
    item = (
        await session.execute(
            select(AuctionItem)
            .where(
                AuctionItem.id == item_id,
                AuctionItem.status == "running",
                AuctionItem.end_at.is_not(None),
                AuctionItem.end_at <= now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        return None
    setting = await get_or_create_setting(session, item.chat_id)
    winner_bid, note = await _resolve_settlement_winner(session, item=item, points_mode=setting.points_mode)
    item.status = "ended"
    item.updated_at = now
    if winner_bid is not None:
        item.winner_user_id = winner_bid.bid_user_id
        item.winner_bid_id = winner_bid.id
        item.current_price = winner_bid.bid_amount
    await session.flush()
    return AuctionSettlementResult(
        item=item,
        winner_user_id=item.winner_user_id,
        winning_amount=item.current_price,
        note=note,
    )
