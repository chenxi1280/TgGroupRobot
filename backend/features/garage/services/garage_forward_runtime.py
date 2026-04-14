from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.alliance import GarageForwardAuditLog, GarageForwardMessageMap


class GarageForwardRuntimeMixin:
    _STALE_FORWARD_SLOT_TTL = dt.timedelta(minutes=10)

    @staticmethod
    async def already_forwarded(
        session: AsyncSession,
        *,
        chat_id: int,
        source_channel_id: int,
        source_message_id: int,
    ) -> bool:
        result = await session.execute(
            select(GarageForwardMessageMap).where(
                GarageForwardMessageMap.chat_id == chat_id,
                GarageForwardMessageMap.source_channel_id == source_channel_id,
                GarageForwardMessageMap.source_message_id == source_message_id,
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def claim_forward_slot(
        session: AsyncSession,
        *,
        chat_id: int,
        source_channel_id: int,
        source_message_id: int,
    ) -> GarageForwardMessageMap | None:
        result = await session.execute(
            select(GarageForwardMessageMap).where(
                GarageForwardMessageMap.chat_id == chat_id,
                GarageForwardMessageMap.source_channel_id == source_channel_id,
                GarageForwardMessageMap.source_message_id == source_message_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            is_stale_placeholder = (
                int(existing.target_message_id or 0) == 0
                and existing.forwarded_at <= dt.datetime.now(dt.UTC) - GarageForwardRuntimeMixin._STALE_FORWARD_SLOT_TTL
            )
            if is_stale_placeholder:
                await session.delete(existing)
                await session.flush()
            else:
                return None

        item = GarageForwardMessageMap(
            chat_id=chat_id,
            source_channel_id=source_channel_id,
            source_message_id=source_message_id,
            target_message_id=0,
        )
        session.add(item)
        try:
            await session.flush()
            return item
        except IntegrityError:
            await session.rollback()
            return None

    @staticmethod
    async def finalize_forward(
        session: AsyncSession,
        *,
        message_map_id: int,
        target_message_id: int,
    ) -> GarageForwardMessageMap | None:
        item = await session.get(GarageForwardMessageMap, message_map_id)
        if item is None:
            return None
        item.target_message_id = target_message_id
        item.forwarded_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def abandon_forward_slot(session: AsyncSession, *, message_map_id: int) -> bool:
        item = await session.get(GarageForwardMessageMap, message_map_id)
        if item is None:
            return False
        await session.delete(item)
        await session.flush()
        return True

    @staticmethod
    async def append_audit(
        session: AsyncSession,
        *,
        chat_id: int,
        source_channel_id: int,
        action: str,
        result: str,
        reason: str | None = None,
        source_message_id: int | None = None,
    ) -> None:
        session.add(
            GarageForwardAuditLog(
                chat_id=chat_id,
                source_channel_id=source_channel_id,
                source_message_id=source_message_id,
                action=action,
                result=result,
                reason=reason,
            )
        )
        await session.flush()

    @staticmethod
    async def list_audits(
        session: AsyncSession,
        *,
        chat_id: int,
        result: str = "all",
        limit: int = 20,
    ) -> list[GarageForwardAuditLog]:
        stmt = select(GarageForwardAuditLog).where(GarageForwardAuditLog.chat_id == chat_id)
        if result and result != "all":
            stmt = stmt.where(GarageForwardAuditLog.result == result)
        res = await session.execute(stmt.order_by(GarageForwardAuditLog.id.desc()).limit(limit))
        return list(res.scalars().all())

    @staticmethod
    async def count_audits_by_result(session: AsyncSession, *, chat_id: int) -> dict[str, int]:
        res = await session.execute(
            select(GarageForwardAuditLog.result, func.count(GarageForwardAuditLog.id))
            .where(GarageForwardAuditLog.chat_id == chat_id)
            .group_by(GarageForwardAuditLog.result)
        )
        stats: dict[str, int] = {"all": 0, "success": 0, "skipped": 0, "failed": 0}
        for result, count in res.all():
            key = str(result or "")
            stats[key] = int(count or 0)
        stats["all"] = sum(v for k, v in stats.items() if k != "all")
        return stats

    @staticmethod
    async def list_recent_message_maps(
        session: AsyncSession,
        *,
        chat_id: int,
        limit: int = 20,
    ) -> list[GarageForwardMessageMap]:
        result = await session.execute(
            select(GarageForwardMessageMap)
            .where(GarageForwardMessageMap.chat_id == chat_id)
            .order_by(GarageForwardMessageMap.forwarded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
