from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.alliance import (
    GarageForwardAuditLog,
    GarageForwardMessageMap,
    GarageForwardSetting,
    GarageForwardSource,
)


class GarageForwardService:
    _STALE_FORWARD_SLOT_TTL = dt.timedelta(minutes=10)

    @staticmethod
    async def ensure_setting(session: AsyncSession, chat_id: int) -> GarageForwardSetting:
        setting = await session.get(GarageForwardSetting, chat_id)
        if setting is None:
            setting = GarageForwardSetting(chat_id=chat_id)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def update_setting(
        session: AsyncSession,
        chat_id: int,
        *,
        enabled: bool | None = None,
        sync_mode: str | None = None,
        keyword_rules: list[str] | None = None,
    ) -> GarageForwardSetting:
        setting = await GarageForwardService.ensure_setting(session, chat_id)
        if enabled is not None:
            setting.enabled = enabled
        if sync_mode is not None:
            setting.sync_mode = sync_mode
        if keyword_rules is not None:
            setting.keyword_rules = keyword_rules
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def list_sources(session: AsyncSession, chat_id: int) -> list[GarageForwardSource]:
        result = await session.execute(
            select(GarageForwardSource)
            .where(GarageForwardSource.chat_id == chat_id)
            .order_by(GarageForwardSource.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_source(
        session: AsyncSession,
        *,
        chat_id: int,
        source_channel_id: int,
        source_name: str | None = None,
    ) -> GarageForwardSource:
        result = await session.execute(
            select(GarageForwardSource).where(
                GarageForwardSource.chat_id == chat_id,
                GarageForwardSource.source_channel_id == source_channel_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.enabled = True
            if source_name:
                existing.source_name = source_name
            await session.flush()
            return existing

        item = GarageForwardSource(
            chat_id=chat_id,
            source_channel_id=source_channel_id,
            source_name=source_name,
            enabled=True,
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def remove_source(session: AsyncSession, *, chat_id: int, source_id: int) -> bool:
        item = await session.get(GarageForwardSource, source_id)
        if item is None or item.chat_id != chat_id:
            return False
        await session.delete(item)
        await session.flush()
        return True

    @staticmethod
    async def list_destinations_by_source(
        session: AsyncSession,
        source_channel_id: int,
    ) -> list[tuple[GarageForwardSetting, GarageForwardSource]]:
        result = await session.execute(
            select(GarageForwardSetting, GarageForwardSource)
            .join(GarageForwardSource, GarageForwardSource.chat_id == GarageForwardSetting.chat_id)
            .where(
                GarageForwardSetting.enabled.is_(True),
                GarageForwardSource.enabled.is_(True),
                GarageForwardSource.source_channel_id == source_channel_id,
            )
            .order_by(GarageForwardSource.chat_id.asc(), GarageForwardSource.id.asc())
        )
        return list(result.all())

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
    def should_forward(sync_mode: str, text: str | None, has_media: bool) -> bool:
        normalized = (sync_mode or "all").strip().lower()
        content = (text or "").strip()
        if normalized == "all":
            return True
        if normalized == "text":
            return bool(content) and not has_media
        if normalized == "media":
            return has_media
        if normalized == "keyword":
            return bool(content)
        return False

    @staticmethod
    def matches_keywords(text: str | None, keyword_rules: list | None) -> bool:
        content = (text or "").strip().lower()
        if not content:
            return False
        rules = [str(item).strip().lower() for item in (keyword_rules or []) if str(item).strip()]
        if not rules:
            return False
        return any(rule in content for rule in rules)

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
                and existing.forwarded_at <= dt.datetime.now(dt.UTC) - GarageForwardService._STALE_FORWARD_SLOT_TTL
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
        res = await session.execute(
            stmt.order_by(GarageForwardAuditLog.id.desc()).limit(limit)
        )
        return list(res.scalars().all())

    @staticmethod
    async def count_audits_by_result(
        session: AsyncSession,
        *,
        chat_id: int,
    ) -> dict[str, int]:
        res = await session.execute(
            select(GarageForwardAuditLog.result, func.count(GarageForwardAuditLog.id))
            .where(GarageForwardAuditLog.chat_id == chat_id)
            .group_by(GarageForwardAuditLog.result)
        )
        stats: dict[str, int] = {"all": 0, "success": 0, "skipped": 0, "failed": 0}
        for result, count in res.all():
            key = str(result or "")
            if key in stats:
                stats[key] = int(count or 0)
            else:
                stats[key] = int(count or 0)
        stats["all"] = sum(v for k, v in stats.items() if k != "all")
        return stats
