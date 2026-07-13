from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import CarReviewCustomField, CarReviewSetting
from backend.shared.services.base import ValidationError


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

    @staticmethod
    async def add_custom_field(
        session: AsyncSession,
        chat_id: int,
        *,
        field_key: str,
        field_label: str,
    ) -> CarReviewCustomField:
        await CarReviewSettingsMixin.ensure_default_fields(session, chat_id)
        normalized_key = _normalize_custom_field_key(field_key)
        normalized_label = _normalize_custom_field_label(field_label)
        result = await session.execute(
            select(CarReviewCustomField).where(
                CarReviewCustomField.chat_id == chat_id,
                CarReviewCustomField.field_key == normalized_key,
            )
        )
        item = result.scalar_one_or_none()
        if item is not None:
            item.field_label = normalized_label
            item.enabled = True
            item.updated_at = dt.datetime.now(dt.UTC)
            await session.flush()
            return item

        max_order = await session.execute(
            select(func.max(CarReviewCustomField.sort_order)).where(CarReviewCustomField.chat_id == chat_id)
        )
        item = CarReviewCustomField(
            chat_id=chat_id,
            field_key=normalized_key,
            field_label=normalized_label,
            enabled=True,
            sort_order=int(max_order.scalar_one_or_none() or 0) + 1,
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def update_custom_field_label(
        session: AsyncSession,
        chat_id: int,
        field_id: int,
        *, field_label: str,
    ) -> CarReviewCustomField | None:
        item = await session.get(CarReviewCustomField, field_id)
        if item is None or item.chat_id != chat_id:
            return None
        item.field_label = _normalize_custom_field_label(field_label)
        item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def toggle_custom_field(
        session: AsyncSession,
        chat_id: int,
        field_id: int,
        *,
        enabled: bool | None = None,
    ) -> CarReviewCustomField | None:
        item = await session.get(CarReviewCustomField, field_id)
        if item is None or item.chat_id != chat_id:
            return None
        item.enabled = (not item.enabled) if enabled is None else bool(enabled)
        item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item


def _normalize_custom_field_key(value: str) -> str:
    cleaned = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", cleaned):
        raise ValidationError("字段键只能使用英文字母、数字和下划线，并且必须以字母开头。")
    return cleaned


def _normalize_custom_field_label(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value or "").strip()
    if not cleaned:
        raise ValidationError("字段名称不能为空。")
    if len(cleaned) > 32:
        raise ValidationError("字段名称过长，请控制在 32 个字符以内。")
    return cleaned
