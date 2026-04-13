from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.features.nearby.services.nearby_profile_service import (
    build_user_display_name,
    format_distance,
    haversine_distance_km,
)
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import (
    MemberLocation,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
)


class TeacherSearchService:
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
        setting = await TeacherSearchService.ensure_setting(session, chat_id)
        for key, value in updates.items():
            setattr(setting, key, value)
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def get_setting(session: AsyncSession, chat_id: int) -> TeacherSearchSetting:
        return await TeacherSearchService.ensure_setting(session, chat_id)

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
            select(MemberLocation).where(
                MemberLocation.chat_id == chat_id,
                MemberLocation.user_id == user_id,
            )
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
            select(TeacherProfile).where(
                TeacherProfile.chat_id == chat_id,
                TeacherProfile.user_id == user_id,
            )
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
    async def resolve_delegate_user(session: AsyncSession, raw: str) -> TgUser:
        return await _resolve_user(session, raw)

    @staticmethod
    async def list_open_course_teachers(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[TeacherProfile, TgUser | None]]:
        result = await session.execute(
            select(TeacherProfile, TgUser)
            .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
            .where(TeacherProfile.chat_id == chat_id, TeacherProfile.open_course_today.is_(True))
            .order_by(TeacherProfile.updated_at.desc())
        )
        return list(result.all())

    @staticmethod
    async def get_member_location(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> MemberLocation | None:
        result = await session.execute(
            select(MemberLocation).where(
                MemberLocation.chat_id == chat_id,
                MemberLocation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def search_teachers_by_keyword(
        session: AsyncSession,
        chat_id: int,
        keyword: str,
        *,
        only_open_course: bool = True,
        limit: int = 10,
    ) -> list[tuple[TeacherProfile, TgUser | None]]:
        normalized = keyword.strip().lower()
        if not normalized:
            return []
        rows = (
            await TeacherSearchService.list_open_course_teachers(session, chat_id)
            if only_open_course
            else list(
                (
                    await session.execute(
                        select(TeacherProfile, TgUser)
                        .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
                        .where(TeacherProfile.chat_id == chat_id)
                        .order_by(TeacherProfile.updated_at.desc())
                    )
                ).all()
            )
        )
        matches: list[tuple[TeacherProfile, TgUser | None]] = []
        for profile, user in rows:
            parts = [
                profile.region_text or "",
                profile.price_text or "",
                " ".join(profile.labels or []),
                user.username or "" if user else "",
                user.first_name or "" if user else "",
            ]
            haystack = " ".join(parts).lower()
            if normalized in haystack:
                matches.append((profile, user))
        return matches[:limit]

    @staticmethod
    async def list_nearby_teachers(
        session: AsyncSession,
        chat_id: int,
        latitude: float,
        longitude: float,
        *,
        only_open_course: bool = True,
        limit: int = 10,
    ) -> list[dict]:
        rows = (
            await TeacherSearchService.list_open_course_teachers(session, chat_id)
            if only_open_course
            else list(
                (
                    await session.execute(
                        select(TeacherProfile, TgUser)
                        .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
                        .where(TeacherProfile.chat_id == chat_id)
                        .order_by(TeacherProfile.updated_at.desc())
                    )
                ).all()
            )
        )
        items: list[dict] = []
        for profile, user in rows:
            if profile.latitude is None or profile.longitude is None:
                continue
            distance = haversine_distance_km(
                latitude,
                longitude,
                float(profile.latitude),
                float(profile.longitude),
            )
            items.append(
                {
                    "profile": profile,
                    "user": user,
                    "distance_km": distance,
                    "distance_text": format_distance(distance, fuzzy=True),
                    "display_name": (
                        build_user_display_name(user, profile.user_id)
                        if user
                        else f"用户{profile.user_id}"
                    ),
                }
            )
        items.sort(
            key=lambda item: (
                item["distance_km"],
                -(item["profile"].updated_at.timestamp() if item["profile"].updated_at else 0),
            )
        )
        return items[:limit]

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
            select(TeacherProfile).where(
                TeacherProfile.chat_id == chat_id,
                TeacherProfile.user_id == user_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = TeacherProfile(chat_id=chat_id, user_id=user_id)
            session.add(profile)
        profile.open_course_today = True
        profile.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item
