from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_auth_service import GarageAuthService
from backend.features.points.services.points_extended_custom import PointsExtendedCustomMixin
from backend.features.points.services.points_service import get_balance
from backend.platform.db.schema.models.core import PointsLevel, PointsLevelSetting
from backend.shared.services.base import ValidationError


class PointsExtendedLevelsMixin:
    @staticmethod
    async def _ensure_level_threshold_unique(
        session: AsyncSession,
        *,
        chat_id: int,
        point_threshold: int,
        exclude_level_id: int | None = None,
    ) -> None:
        stmt = select(PointsLevel.id).where(
            PointsLevel.chat_id == chat_id,
            PointsLevel.point_threshold == point_threshold,
        )
        if exclude_level_id is not None:
            stmt = stmt.where(PointsLevel.id != exclude_level_id)
        result = await session.execute(stmt.limit(1))
        if result.scalar_one_or_none() is not None:
            raise ValidationError("该积分门槛已存在，请重新设置。")

    @staticmethod
    async def get_or_create_level_setting(session: AsyncSession, chat_id: int) -> PointsLevelSetting:
        result = await session.execute(select(PointsLevelSetting).where(PointsLevelSetting.chat_id == chat_id))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = PointsLevelSetting(chat_id=chat_id, enabled=False, exclude_teacher_enabled=False)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def list_levels(session: AsyncSession, chat_id: int) -> list[PointsLevel]:
        result = await session.execute(
            select(PointsLevel)
            .where(PointsLevel.chat_id == chat_id)
            .order_by(PointsLevel.point_threshold.asc(), PointsLevel.level_no.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_level(session: AsyncSession, chat_id: int, level_id: int) -> PointsLevel | None:
        result = await session.execute(
            select(PointsLevel).where(PointsLevel.chat_id == chat_id, PointsLevel.id == level_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_level(session: AsyncSession, chat_id: int) -> PointsLevel:
        await PointsExtendedCustomMixin._lock_chat_scope(session, chat_id)
        next_no_result = await session.execute(
            select(func.coalesce(func.max(PointsLevel.level_no), 0) + 1).where(PointsLevel.chat_id == chat_id)
        )
        next_no = int(next_no_result.scalar_one())
        max_threshold_result = await session.execute(
            select(func.coalesce(func.max(PointsLevel.point_threshold), 0)).where(PointsLevel.chat_id == chat_id)
        )
        next_threshold = int(max_threshold_result.scalar_one()) + 1
        level = PointsLevel(
            chat_id=chat_id,
            level_no=next_no,
            level_name="待配置" if next_no == 1 else f"待配置{next_no}",
            point_threshold=next_threshold,
            enabled=True,
        )
        session.add(level)
        await session.flush()
        return level

    @staticmethod
    async def update_level_setting(
        session: AsyncSession,
        setting: PointsLevelSetting,
        *,
        enabled: bool | None = None,
        exclude_teacher_enabled: bool | None = None,
    ) -> PointsLevelSetting:
        if enabled is not None:
            setting.enabled = enabled
        if exclude_teacher_enabled is not None:
            setting.exclude_teacher_enabled = exclude_teacher_enabled
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def update_level(
        session: AsyncSession,
        level: PointsLevel,
        *,
        level_name: str | None = None,
        point_threshold: int | None = None,
        perm_name: str | None = None,
        perm_value: bool | None = None,
    ) -> PointsLevel:
        if level_name is not None:
            normalized_name = level_name.strip()
            if not normalized_name:
                raise ValidationError("等级名称不能为空。")
            level.level_name = normalized_name
        if point_threshold is not None:
            if int(point_threshold) <= 0:
                raise ValidationError("积分门槛必须大于 0。")
            await PointsExtendedLevelsMixin._ensure_level_threshold_unique(
                session,
                chat_id=level.chat_id,
                point_threshold=int(point_threshold),
                exclude_level_id=level.id,
            )
            level.point_threshold = point_threshold
        if perm_name is not None and perm_value is not None and hasattr(level, perm_name):
            setattr(level, perm_name, perm_value)
        level.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return level

    @staticmethod
    async def delete_level(session: AsyncSession, level: PointsLevel) -> None:
        await session.delete(level)
        await session.flush()

    @staticmethod
    async def resolve_user_level(session: AsyncSession, chat_id: int, user_id: int) -> PointsLevel | None:
        setting = await PointsExtendedLevelsMixin.get_or_create_level_setting(session, chat_id)
        if not setting.enabled:
            return None
        balance = await get_balance(session, chat_id, user_id)
        result = await session.execute(
            select(PointsLevel)
            .where(
                PointsLevel.chat_id == chat_id,
                PointsLevel.enabled.is_(True),
                PointsLevel.point_threshold <= balance,
            )
            .order_by(PointsLevel.point_threshold.desc(), PointsLevel.level_no.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def is_teacher_exempt(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        return await GarageAuthService.has_effective_teacher_profile(session, chat_id, user_id)
