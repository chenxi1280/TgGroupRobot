from __future__ import annotations

import datetime as dt

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.auction_time import as_utc, now_utc
from backend.platform.db.schema.models.expansion import AuctionBid, AuctionItem
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.user_service import ensure_user


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
    await ensure_user(session, creator_user_id, None, first_name=None, last_name=None, language_code=None)
    item = AuctionItem(
        chat_id=chat_id,
        creator_user_id=creator_user_id,
        source_message_id=source_message_id,
        title=title.strip(),
        start_price=start_price,
        current_price=start_price,
        status="running",
        start_at=now_utc(),
        end_at=as_utc(end_at),
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
