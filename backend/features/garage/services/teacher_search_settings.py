from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import MemberLocation, TeacherDailyAttendance, TeacherProfile, TeacherSearchSetting
from backend.shared.services.base import ValidationError
from backend.shared.time_helper import LOCAL_TIMEZONE


@dataclass(frozen=True)
class TeacherSearchFooterButtonConfig:
    button_text: str | None
    button_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.button_text or self.button_url)


def _clean_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    return cleaned or None


def _clean_required_keyword(value: str, *, label: str) -> str:
    cleaned = _clean_optional_value(value)
    if cleaned is None:
        raise ValidationError(f"{label}不能为空。")
    if len(cleaned) > 16:
        raise ValidationError(f"{label}过长，请控制在 16 个字符以内。")
    return cleaned


def _footer_config_from_setting(setting: TeacherSearchSetting) -> TeacherSearchFooterButtonConfig:
    return TeacherSearchFooterButtonConfig(
        button_text=(setting.footer_button_label or "").strip() or None,
        button_url=(getattr(setting, "footer_button_url", None) or "").strip() or None,
    )


def _teacher_search_biz_date() -> dt.date:
    return dt.datetime.now(dt.UTC).astimezone(LOCAL_TIMEZONE).date()


class TeacherSearchSettingsMixin:
    @staticmethod
    async def ensure_setting(session: AsyncSession, chat_id: int) -> TeacherSearchSetting:
        setting = await session.get(TeacherSearchSetting, chat_id)
        if setting is None:
            setting = TeacherSearchSetting(chat_id=chat_id)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def update_setting(session: AsyncSession, chat_id: int, **updates) -> TeacherSearchSetting:
        setting = await TeacherSearchSettingsMixin.ensure_setting(session, chat_id)
        for key, value in updates.items():
            setattr(setting, key, value)
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def get_setting(session: AsyncSession, chat_id: int) -> TeacherSearchSetting:
        return await TeacherSearchSettingsMixin.ensure_setting(session, chat_id)

    @staticmethod
    async def get_footer_button_config(
        session: AsyncSession,
        chat_id: int,
    ) -> TeacherSearchFooterButtonConfig:
        setting = await TeacherSearchSettingsMixin.ensure_setting(session, chat_id)
        return _footer_config_from_setting(setting)

    @staticmethod
    async def update_footer_button_text(
        session: AsyncSession,
        chat_id: int,
        button_text: str | None,
    ) -> TeacherSearchFooterButtonConfig:
        label = _clean_optional_value(button_text)
        if label is not None and len(label) > 16:
            raise ValidationError("底部按钮名称过长，请控制在 16 个字符以内。")
        setting = await TeacherSearchSettingsMixin.update_setting(session, chat_id, footer_button_label=label)
        return _footer_config_from_setting(setting)

    @staticmethod
    async def update_footer_button_url(
        session: AsyncSession,
        chat_id: int,
        button_url: str | None,
    ) -> TeacherSearchFooterButtonConfig:
        url = _clean_optional_value(button_url)
        if url is not None:
            if len(url) > 512:
                raise ValidationError("按钮链接过长，请控制在 512 个字符以内。")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValidationError("按钮链接必须以 http:// 或 https:// 开头。")
        setting = await TeacherSearchSettingsMixin.update_setting(session, chat_id, footer_button_url=url)
        return _footer_config_from_setting(setting)

    @staticmethod
    async def update_attendance_keyword(
        session: AsyncSession,
        chat_id: int,
        kind: str,
        keyword: str,
    ) -> TeacherSearchSetting:
        field_map = {
            "open": ("attendance_open_keyword", "开课词"),
            "full": ("attendance_full_keyword", "满课词"),
            "rest": ("attendance_rest_keyword", "休息词"),
        }
        if kind not in field_map:
            raise ValidationError("无效打卡词类型。")
        field_name, label = field_map[kind]
        return await TeacherSearchSettingsMixin.update_setting(
            session,
            chat_id,
            **{field_name: _clean_required_keyword(keyword, label=label)},
        )

    @staticmethod
    async def clear_footer_button_config(
        session: AsyncSession,
        chat_id: int,
    ) -> TeacherSearchFooterButtonConfig:
        setting = await TeacherSearchSettingsMixin.update_setting(
            session,
            chat_id,
            footer_button_label=None,
            footer_button_url=None,
        )
        return _footer_config_from_setting(setting)

    @staticmethod
    async def resolve_delegate_user(session: AsyncSession, raw: str) -> TgUser:
        return await _resolve_user(session, raw)

    @staticmethod
    async def upsert_member_location(
        session: AsyncSession,
        *,
        chat_id: int,
        user_id: int,
        latitude: float,
        longitude: float,
        operator_user_id: int | None,
        address_text: str | None = None,
    ) -> MemberLocation:
        result = await session.execute(
            select(MemberLocation).where(MemberLocation.chat_id == chat_id, MemberLocation.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = MemberLocation(
                chat_id=chat_id,
                user_id=user_id,
                latitude=Decimal(str(latitude)),
                longitude=Decimal(str(longitude)),
                updated_by_user_id=operator_user_id,
            )
            session.add(item)
        else:
            item.latitude = Decimal(str(latitude))
            item.longitude = Decimal(str(longitude))
            item.updated_by_user_id = operator_user_id
            item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def upsert_teacher_profile_from_location(
        session: AsyncSession,
        *,
        chat_id: int,
        user_id: int,
        latitude: float,
        longitude: float,
    ) -> TeacherProfile:
        result = await session.execute(
            select(TeacherProfile).where(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = TeacherProfile(
                chat_id=chat_id,
                user_id=user_id,
                latitude=Decimal(str(latitude)),
                longitude=Decimal(str(longitude)),
                last_location_at=dt.datetime.now(dt.UTC),
            )
            session.add(item)
        else:
            item.latitude = Decimal(str(latitude))
            item.longitude = Decimal(str(longitude))
            item.last_location_at = dt.datetime.now(dt.UTC)
            item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def get_member_location(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> MemberLocation | None:
        result = await session.execute(
            select(MemberLocation).where(MemberLocation.chat_id == chat_id, MemberLocation.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_teacher_profile(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> TeacherProfile | None:
        result = await session.execute(
            select(TeacherProfile).where(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def has_recorded_teacher_location(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> bool:
        member_location = await TeacherSearchSettingsMixin.get_member_location(session, chat_id, user_id)
        if member_location is not None:
            return True
        profile = await TeacherSearchSettingsMixin.get_teacher_profile(session, chat_id, user_id)
        return bool(profile and profile.latitude is not None and profile.longitude is not None)

    @staticmethod
    async def reset_stale_open_course_flags(session: AsyncSession) -> int:
        today = _teacher_search_biz_date()
        result = await session.execute(
            update(TeacherProfile)
            .where(TeacherProfile.open_course_today.is_(True))
            .where(
                ~select(TeacherDailyAttendance.id)
                .where(
                    TeacherDailyAttendance.chat_id == TeacherProfile.chat_id,
                    TeacherDailyAttendance.user_id == TeacherProfile.user_id,
                    TeacherDailyAttendance.biz_date == today,
                )
                .exists()
            )
            .values(open_course_today=False, open_course_status=None, updated_at=dt.datetime.now(dt.UTC))
        )
        await session.flush()
        return int(result.rowcount or 0)

    @staticmethod
    async def mark_attendance(
        session: AsyncSession,
        *,
        chat_id: int,
        user_id: int,
        source_message_id: int | None,
        status: str = "open",
    ) -> TeacherDailyAttendance:
        if status not in {"open", "full", "rest"}:
            raise ValidationError("无效开课状态。")
        today = _teacher_search_biz_date()
        result = await session.execute(
            select(TeacherDailyAttendance).where(
                TeacherDailyAttendance.chat_id == chat_id,
                TeacherDailyAttendance.user_id == user_id,
                TeacherDailyAttendance.biz_date == today,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = TeacherDailyAttendance(
                chat_id=chat_id,
                user_id=user_id,
                biz_date=today,
                status=status,
                source_message_id=source_message_id,
            )
            session.add(item)
        else:
            item.status = status
            item.source_message_id = source_message_id
        result = await session.execute(
            select(TeacherProfile).where(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = TeacherProfile(chat_id=chat_id, user_id=user_id)
            session.add(profile)
        profile.open_course_today = status != "rest"
        profile.open_course_status = status
        profile.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item
