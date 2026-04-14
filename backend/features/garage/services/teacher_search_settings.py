from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import MemberLocation, TeacherDailyAttendance, TeacherProfile, TeacherSearchSetting


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
    async def mark_attendance(
        session: AsyncSession,
        *,
        chat_id: int,
        user_id: int,
        source_message_id: int | None,
    ) -> TeacherDailyAttendance:
        today = dt.datetime.now(dt.UTC).date()
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
                source_message_id=source_message_id,
            )
            session.add(item)
        result = await session.execute(
            select(TeacherProfile).where(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = TeacherProfile(chat_id=chat_id, user_id=user_id)
            session.add(profile)
        profile.open_course_today = True
        profile.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item
