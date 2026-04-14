from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import CarReviewCustomField, CarReviewSetting


class CarReviewSettingsMixin:
    DEFAULT_FIELDS: tuple[tuple[str, str], ...] = (
        ("photo_score", "人照"),
        ("face_score", "颜值"),
        ("body_score", "身材"),
        ("service_score", "服务"),
        ("attitude_score", "态度"),
        ("env_score", "环境"),
        ("process", "过程"),
    )

    @staticmethod
    async def ensure_setting(session: AsyncSession, chat_id: int) -> CarReviewSetting:
        setting = await session.get(CarReviewSetting, chat_id)
        if setting is None:
            setting = CarReviewSetting(chat_id=chat_id)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def ensure_default_fields(session: AsyncSession, chat_id: int) -> None:
        for field_key, field_label in CarReviewSettingsMixin.DEFAULT_FIELDS:
            result = await session.execute(
                select(CarReviewCustomField).where(
                    CarReviewCustomField.chat_id == chat_id,
                    CarReviewCustomField.field_key == field_key,
                )
            )
            item = result.scalar_one_or_none()
            if item is None:
                session.add(
                    CarReviewCustomField(
                        chat_id=chat_id,
                        field_key=field_key,
                        field_label=field_label,
                        enabled=True,
                    )
                )
        await session.flush()

    @staticmethod
    async def get_setting(session: AsyncSession, chat_id: int) -> CarReviewSetting:
        setting = await CarReviewSettingsMixin.ensure_setting(session, chat_id)
        await CarReviewSettingsMixin.ensure_default_fields(session, chat_id)
        return setting

    @staticmethod
    async def update_setting(session: AsyncSession, chat_id: int, **updates) -> CarReviewSetting:
        setting = await CarReviewSettingsMixin.get_setting(session, chat_id)
        for key, value in updates.items():
            setattr(setting, key, value)
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def resolve_approver(session: AsyncSession, raw: str) -> TgUser:
        return await _resolve_user(session, raw)

    @staticmethod
    async def list_custom_fields(session: AsyncSession, chat_id: int) -> list[CarReviewCustomField]:
        await CarReviewSettingsMixin.ensure_default_fields(session, chat_id)
        result = await session.execute(
            select(CarReviewCustomField)
            .where(CarReviewCustomField.chat_id == chat_id)
            .order_by(CarReviewCustomField.sort_order.asc(), CarReviewCustomField.id.asc())
        )
        return list(result.scalars().all())
