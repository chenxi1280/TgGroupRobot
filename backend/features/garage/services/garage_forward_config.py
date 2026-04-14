from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.schema.models.alliance import GarageForwardSetting, GarageForwardSource
from backend.shared.services.base import ValidationError


class GarageForwardConfigMixin:
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
        button_template_enabled: bool | None = None,
        button_template: list | None = None,
    ) -> GarageForwardSetting:
        setting = await GarageForwardConfigMixin.ensure_setting(session, chat_id)
        if enabled is not None:
            setting.enabled = enabled
        if sync_mode is not None:
            setting.sync_mode = sync_mode
        if keyword_rules is not None:
            setting.keyword_rules = keyword_rules
        if button_template_enabled is not None:
            setting.button_template_enabled = button_template_enabled
        if button_template is not None:
            setting.button_template = GarageForwardConfigMixin.normalize_button_template(button_template)
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
    def normalize_button_template(raw_buttons: list | None) -> list[list[dict[str, str]]]:
        if not raw_buttons:
            return []
        normalized = ScheduledMessageService.normalize_buttons_config(raw_buttons)
        for row in normalized:
            if len(row) > 4:
                raise ValidationError("按钮模板每行最多 4 个按钮")
        if len(normalized) > 6:
            raise ValidationError("按钮模板最多支持 6 行")
        return normalized

    @staticmethod
    def build_button_markup(buttons: list | None) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None
        normalized = GarageForwardConfigMixin.normalize_button_template(buttons)
        keyboard = [[InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row] for row in normalized]
        return InlineKeyboardMarkup(keyboard) if keyboard else None
