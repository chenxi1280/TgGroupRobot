from __future__ import annotations

import datetime as dt
import re

from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_auth_service import GarageAuthService
from backend.features.nearby.services.nearby_profile_service import build_user_display_name, format_distance, haversine_distance_km
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import (
    GarageCertifiedTeacher,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
    TeacherSourcePost,
)
from backend.shared.time_helper import LOCAL_TIMEZONE


@dataclass
class TeacherProfileView:
    user_id: int
    latitude: float | None = None
    longitude: float | None = None
    labels: list[str] | None = None
    region_text: str | None = None
    price_text: str | None = None
    open_course_today: bool = False
    open_course_status: str | None = None
    avg_score: float = 0.0
    review_count: int = 0
    last_location_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    source_profile_id: int | None = None
    source_status: str | None = None
    source_username: str | None = None
    source_channel_title: str | None = None
    source_url: str | None = None
    source_raw_text: str | None = None


def _teacher_search_biz_date() -> dt.date:
    return dt.datetime.now(dt.UTC).astimezone(LOCAL_TIMEZONE).date()


def _build_profile_view(
    user_id: int,
    profile: TeacherProfile | None,
    attendance: TeacherDailyAttendance | None,
) -> TeacherProfileView:
    status = getattr(attendance, "status", None) if attendance is not None else None
    return TeacherProfileView(
        user_id=user_id,
        latitude=getattr(profile, "latitude", None) if profile is not None else None,
        longitude=getattr(profile, "longitude", None) if profile is not None else None,
        labels=list(getattr(profile, "labels", None) or []),
        region_text=getattr(profile, "region_text", None) if profile is not None else None,
        price_text=getattr(profile, "price_text", None) if profile is not None else None,
        open_course_today=status in {"open", "full"},
        open_course_status=status,
        last_location_at=getattr(profile, "last_location_at", None) if profile is not None else None,
        updated_at=getattr(profile, "updated_at", None) if profile is not None else None,
    )


def _build_source_post_view(source_post: TeacherSourcePost) -> TeacherProfileView:
    return TeacherProfileView(
        user_id=int(source_post.teacher_user_id or 0),
        labels=list(getattr(source_post, "labels", None) or []),
        region_text=getattr(source_post, "region_text", None),
        price_text=getattr(source_post, "price_text", None),
        updated_at=getattr(source_post, "updated_at", None),
        source_profile_id=int(source_post.id),
        source_status=getattr(source_post, "bind_status", None),
        source_username=getattr(source_post, "username", None),
        source_channel_title=getattr(source_post, "source_channel_title", None),
        source_url=getattr(source_post, "source_url", None),
        source_raw_text=getattr(source_post, "raw_text", None),
    )


def _attach_source_to_profile(profile: TeacherProfileView, source_profile: TeacherProfileView) -> None:
    profile.source_profile_id = source_profile.source_profile_id
    profile.source_status = source_profile.source_status
    profile.source_username = source_profile.source_username
    profile.source_channel_title = source_profile.source_channel_title
    profile.source_url = source_profile.source_url
    profile.source_raw_text = source_profile.source_raw_text


def teacher_attendance_status_label(profile: TeacherProfile | TeacherProfileView | None) -> str:
    status = getattr(profile, "open_course_status", None)
    return {
        "open": "开课中",
        "full": "满课",
        "rest": "休息",
    }.get(status, "未开课")


def teacher_profile_completeness_label(profile: TeacherProfile | TeacherProfileView | None) -> str:
    if profile is None:
        return "未定位，资料待完善"
    has_location = getattr(profile, "latitude", None) is not None and getattr(profile, "longitude", None) is not None
    has_profile_text = bool(
        (getattr(profile, "region_text", None) or "").strip()
        or (getattr(profile, "price_text", None) or "").strip()
        or (getattr(profile, "labels", None) or [])
    )
    location_label = "已定位" if has_location else "未定位"
    profile_label = "资料完整" if has_profile_text else "资料待完善"
    return f"{location_label}，{profile_label}"


def _normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _keyword_price_ranges(normalized_keyword: str) -> list[tuple[float, float]]:
    if not re.search(r"(左右|上下|附近|以内|以下|之内)", normalized_keyword):
        return []
    ranges: list[tuple[float, float]] = []
    for raw in re.findall(r"\d+(?:\.\d+)?", normalized_keyword):
        value = float(raw)
        if "以内" in normalized_keyword or "以下" in normalized_keyword or "之内" in normalized_keyword:
            ranges.append((0, value))
        else:
            ranges.append((max(0, value - 100), value + 100))
    return ranges


def _keyword_score_threshold(normalized_keyword: str) -> float | None:
    if normalized_keyword in {"高分", "高评分", "高评价"}:
        return 90.0
    if not re.search(r"(分|评分|均分|score|>=|以上|不低于)", normalized_keyword):
        return None
    match = re.search(r"(?:评分|均分|score)?(?:>=|不低于)?(\d+(?:\.\d+)?)(?:分)?(?:以上)?", normalized_keyword)
    if match is None:
        return None
    return float(match.group(1))


def _teacher_score_matches(profile: TeacherProfileView, normalized_keyword: str) -> bool:
    threshold = _keyword_score_threshold(normalized_keyword)
    if threshold is None:
        return False
    return int(getattr(profile, "review_count", 0) or 0) > 0 and float(getattr(profile, "avg_score", 0.0) or 0.0) >= threshold


def _teacher_keyword_parts(profile: TeacherProfileView, user: TgUser | None) -> list[str]:
    first_name = (user.first_name or "") if user else ""
    last_name = (user.last_name or "") if user else ""
    return [
        str(profile.user_id),
        profile.region_text or "",
        profile.price_text or "",
        " ".join(profile.labels or []),
        f"{float(getattr(profile, 'avg_score', 0.0) or 0.0):g}分"
        if int(getattr(profile, "review_count", 0) or 0)
        else "",
        user.username or "" if user else "",
        first_name,
        last_name,
        "".join([first_name, last_name]),
        " ".join(part for part in [first_name, last_name] if part),
        getattr(profile, "source_username", None) or "",
        getattr(profile, "source_channel_title", None) or "",
        getattr(profile, "source_raw_text", None) or "",
    ]


def _keyword_numbers_match(parts: list[str], normalized_keyword: str) -> bool:
    keyword_numbers = re.findall(r"\d+(?:\.\d+)?", normalized_keyword)
    if not keyword_numbers:
        return False
    numeric_haystack = " ".join(parts)
    haystack_numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", numeric_haystack)]
    if any(lower <= number <= upper for lower, upper in _keyword_price_ranges(normalized_keyword) for number in haystack_numbers):
        return True
    haystack_number_text = {str(int(number)) if number.is_integer() else str(number) for number in haystack_numbers}
    return any(number in haystack_number_text for number in keyword_numbers)


def _teacher_keyword_matches(
    profile: TeacherProfileView,
    user: TgUser | None,
    keyword: str,
) -> bool:
    normalized = _normalize_search_text(keyword)
    if not normalized:
        return False
    if _keyword_score_threshold(normalized) is not None:
        return _teacher_score_matches(profile, normalized)

    parts = _teacher_keyword_parts(profile, user)
    haystacks = [_normalize_search_text(part) for part in parts if part]
    if any(normalized in haystack for haystack in haystacks):
        return True

    if _keyword_numbers_match(parts, normalized):
        return True

    if _teacher_score_matches(profile, normalized):
        return True

    return False


class TeacherSearchQueryMixin:
    @staticmethod
    async def _filter_effective_teacher_rows(
        session: AsyncSession,
        chat_id: int,
        rows: list[tuple[TeacherProfile, TgUser | None]],
    ) -> list[tuple[TeacherProfile, TgUser | None]]:
        filtered: list[tuple[TeacherProfile, TgUser | None]] = []
        for profile, user in rows:
            if await GarageAuthService.is_effective_certified_teacher(session, chat_id, profile.user_id):
                filtered.append((profile, user))
        return filtered

    @staticmethod
    async def get_attendance_source_chat_id(session: AsyncSession, chat_id: int) -> int:
        setting = await session.get(TeacherSearchSetting, chat_id)
        if (
            setting is not None
            and setting.attendance_mode == "external"
            and setting.attendance_source_chat_id is not None
        ):
            return int(setting.attendance_source_chat_id)
        return chat_id

    @staticmethod
    async def is_certified_teacher_for_attendance_source(
        session: AsyncSession,
        source_chat_id: int,
        user_id: int,
    ) -> bool:
        result = await session.execute(
            select(TeacherSearchSetting.chat_id).where(
                TeacherSearchSetting.attendance_enabled.is_(True),
                TeacherSearchSetting.attendance_mode == "external",
                TeacherSearchSetting.attendance_source_chat_id == source_chat_id,
            )
        )
        target_chat_ids = [int(chat_id) for chat_id in result.scalars().all()]
        for target_chat_id in target_chat_ids:
            if await GarageAuthService.is_effective_certified_teacher(session, target_chat_id, user_id):
                return True
        return False

    @staticmethod
    async def list_open_course_teachers(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[TeacherProfileView, TgUser | None]]:
        rows = await TeacherSearchQueryMixin.list_searchable_teachers(
            session,
            chat_id,
            only_open_course=True,
        )
        return rows

    @staticmethod
    async def list_searchable_teachers(
        session: AsyncSession,
        chat_id: int,
        *,
        only_open_course: bool = False,
    ) -> list[tuple[TeacherProfileView, TgUser | None]]:
        today = _teacher_search_biz_date()
        pool_chat_id = await GarageAuthService.resolve_teacher_pool_chat_id(session, chat_id)
        attendance_chat_id = await TeacherSearchQueryMixin.get_attendance_source_chat_id(session, chat_id)
        rows = await TeacherSearchQueryMixin._list_certified_teacher_rows(
            session,
            chat_id=chat_id,
            pool_chat_id=pool_chat_id,
            attendance_chat_id=attendance_chat_id,
            today=today,
            only_open_course=only_open_course,
        )
        await TeacherSearchQueryMixin._attach_review_stats(session, chat_id, rows)
        if not only_open_course:
            rows = await TeacherSearchQueryMixin._merge_source_post_rows(session, chat_id, rows)
        return rows

    @staticmethod
    async def _list_certified_teacher_rows(
        session: AsyncSession,
        *,
        chat_id: int,
        pool_chat_id: int,
        attendance_chat_id: int,
        today: dt.date,
        only_open_course: bool,
    ) -> list[tuple[TeacherProfileView, TgUser | None]]:
        result = await session.execute(
            select(GarageCertifiedTeacher, TeacherProfile, TgUser, TeacherDailyAttendance)
            .join(TeacherProfile, (TeacherProfile.chat_id == chat_id) & (TeacherProfile.user_id == GarageCertifiedTeacher.user_id), isouter=True)
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .join(TeacherDailyAttendance, (TeacherDailyAttendance.chat_id == attendance_chat_id) & (TeacherDailyAttendance.user_id == GarageCertifiedTeacher.user_id) & (TeacherDailyAttendance.biz_date == today), isouter=True)
            .where(GarageCertifiedTeacher.chat_id == pool_chat_id, GarageCertifiedTeacher.enabled.is_(True))
            .order_by(TeacherDailyAttendance.created_at.desc().nullslast(), TeacherProfile.updated_at.desc().nullslast(), GarageCertifiedTeacher.created_at.asc(), GarageCertifiedTeacher.id.asc())
        )
        rows = []
        for teacher, profile, user, attendance in result.all():
            profile_view = _build_profile_view(teacher.user_id, profile, attendance)
            if only_open_course and getattr(profile_view, "open_course_status", None) not in {"open", "full"}:
                continue
            rows.append((profile_view, user))
        return rows

    @staticmethod
    async def _attach_review_stats(
        session: AsyncSession,
        chat_id: int,
        rows: list[tuple[TeacherProfileView, TgUser | None]],
    ) -> None:
        if not rows:
            return
        from backend.features.garage.services.car_review_reports import CarReviewReportMixin

        stats_map = await CarReviewReportMixin.get_teacher_review_stats_map(
            session,
            chat_id,
            [profile.user_id for profile, _user in rows if profile.user_id],
        )
        for profile, _user in rows:
            stats = stats_map.get(profile.user_id) or {}
            profile.review_count = int(stats.get("count", 0) or 0)
            profile.avg_score = float(stats.get("avg_score", 0.0) or 0.0)

    @staticmethod
    async def _merge_source_post_rows(
        session: AsyncSession,
        chat_id: int,
        rows: list[tuple[TeacherProfileView, TgUser | None]],
    ) -> list[tuple[TeacherProfileView, TgUser | None]]:
        result = await session.execute(
            select(TeacherSourcePost, TgUser)
            .join(TgUser, TgUser.id == TeacherSourcePost.teacher_user_id, isouter=True)
            .where(TeacherSourcePost.chat_id == chat_id)
            .order_by(TeacherSourcePost.updated_at.desc().nullslast(), TeacherSourcePost.id.desc())
        )
        source_rows = result.all()
        if not source_rows:
            return rows
        by_user_id = {profile.user_id: profile for profile, _user in rows if profile.user_id}
        merged = list(rows)
        for source_post, user in source_rows:
            source_profile = _build_source_post_view(source_post)
            if source_profile.user_id and source_profile.user_id in by_user_id:
                _attach_source_to_profile(by_user_id[source_profile.user_id], source_profile)
                continue
            merged.append((source_profile, user))
        return merged

    @staticmethod
    async def search_teachers_by_keyword(
        session: AsyncSession,
        chat_id: int,
        keyword: str,
        *,
        only_open_course: bool = True,
        limit: int = 10,
    ) -> list[tuple[TeacherProfileView, TgUser | None]]:
        normalized = keyword.strip().lower()
        if not normalized:
            return []
        from backend.features.garage.services.teacher_search_service import TeacherSearchService

        rows = (
            await TeacherSearchService.list_open_course_teachers(session, chat_id)
            if only_open_course
            else await TeacherSearchQueryMixin.list_searchable_teachers(session, chat_id)
        )
        matches: list[tuple[TeacherProfileView, TgUser | None]] = []
        for profile, user in rows:
            if _teacher_keyword_matches(profile, user, normalized):
                matches.append((profile, user))
        matches.sort(
            key=lambda row: (
                -float(getattr(row[0], "avg_score", 0.0) or 0.0),
                -int(getattr(row[0], "review_count", 0) or 0),
                row[0].user_id or 9_999_999_999,
                getattr(row[0], "source_profile_id", None) or 0,
            )
        )
        return matches[:limit]

    @staticmethod
    async def list_nearby_teachers(
        session: AsyncSession,
        chat_id: int,
        latitude: float,
        longitude: float,
        *,
        only_open_course: bool = True,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        from backend.features.garage.services.teacher_search_service import TeacherSearchService

        rows = (
            await TeacherSearchService.list_open_course_teachers(session, chat_id)
            if only_open_course
            else await TeacherSearchQueryMixin.list_searchable_teachers(session, chat_id)
        )
        items: list[dict] = []
        for profile, user in rows:
            if profile.latitude is None or profile.longitude is None:
                continue
            if keyword and not _teacher_keyword_matches(profile, user, keyword):
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
