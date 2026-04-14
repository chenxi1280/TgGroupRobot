from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.nearby.services.nearby_profile_service import build_user_display_name, format_distance, haversine_distance_km
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import TeacherProfile


class TeacherSearchQueryMixin:
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
        from backend.features.garage.services.teacher_search_service import TeacherSearchService

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
            if normalized in " ".join(parts).lower():
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
        from backend.features.garage.services.teacher_search_service import TeacherSearchService

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
            distance = haversine_distance_km(latitude, longitude, float(profile.latitude), float(profile.longitude))
            items.append(
                {
                    "profile": profile,
                    "user": user,
                    "distance_km": distance,
                    "distance_text": format_distance(distance, fuzzy=True),
                    "display_name": build_user_display_name(user, profile.user_id) if user else f"用户{profile.user_id}",
                }
            )
        items.sort(key=lambda item: (item["distance_km"], -(item["profile"].updated_at.timestamp() if item["profile"].updated_at else 0)))
        return items[:limit]
