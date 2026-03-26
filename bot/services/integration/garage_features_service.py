from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, TgUser
from bot.models.garage_features import (
    CarReviewAuditLog,
    CarReviewCustomField,
    CarReviewReport,
    CarReviewSetting,
    GarageCertifiedTeacher,
    GarageSpeechWhitelist,
    MemberLocation,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
)
from bot.services.base import ServiceBase, ValidationError
from bot.services.core.chat_service import get_chat_settings
from bot.services.integration.nearby_profile_service import (
    build_user_display_name,
    format_distance,
    haversine_distance_km,
)


def _normalize_username_or_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValidationError("输入内容不能为空。")
    return value[1:] if value.startswith("@") else value


async def _resolve_user(session: AsyncSession, raw: str) -> TgUser:
    value = _normalize_username_or_id(raw)
    if value.lstrip("-").isdigit():
        user = await ServiceBase._get_by_id(session, TgUser, int(value))
    else:
        result = await session.execute(select(TgUser).where(TgUser.username == value))
        user = result.scalar_one_or_none()
    if user is None:
        raise ValidationError("未找到该用户，请先让对方与机器人产生交互。")
    return user


class GarageAuthService:
    @staticmethod
    async def get_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
        return await get_chat_settings(session, chat_id)

    @staticmethod
    async def update_settings(session: AsyncSession, chat_id: int, **updates) -> ChatSettings:
        settings = await get_chat_settings(session, chat_id)
        for key, value in updates.items():
            setattr(settings, key, value)
        await session.flush()
        return settings

    @staticmethod
    async def list_certified_teachers(session: AsyncSession, chat_id: int) -> list[tuple[GarageCertifiedTeacher, TgUser | None]]:
        result = await session.execute(
            select(GarageCertifiedTeacher, TgUser)
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .where(GarageCertifiedTeacher.chat_id == chat_id)
            .order_by(GarageCertifiedTeacher.id.asc())
        )
        return list(result.all())

    @staticmethod
    async def add_teacher(session: AsyncSession, chat_id: int, operator_user_id: int, raw: str) -> GarageCertifiedTeacher:
        user = await _resolve_user(session, raw)
        result = await session.execute(
            select(GarageCertifiedTeacher).where(
                GarageCertifiedTeacher.chat_id == chat_id,
                GarageCertifiedTeacher.user_id == user.id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = GarageCertifiedTeacher(
                chat_id=chat_id,
                user_id=user.id,
                certified_by_user_id=operator_user_id,
                enabled=True,
            )
            session.add(item)
        else:
            item.enabled = True
            item.certified_by_user_id = operator_user_id
            item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def remove_teacher(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(GarageCertifiedTeacher).where(
                GarageCertifiedTeacher.chat_id == chat_id,
                GarageCertifiedTeacher.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        await session.delete(item)
        await session.flush()
        return True

    @staticmethod
    async def list_whitelist(session: AsyncSession, chat_id: int) -> list[tuple[GarageSpeechWhitelist, TgUser | None]]:
        result = await session.execute(
            select(GarageSpeechWhitelist, TgUser)
            .join(TgUser, TgUser.id == GarageSpeechWhitelist.user_id, isouter=True)
            .where(GarageSpeechWhitelist.chat_id == chat_id)
            .order_by(GarageSpeechWhitelist.id.asc())
        )
        return list(result.all())

    @staticmethod
    async def add_whitelist(session: AsyncSession, chat_id: int, operator_user_id: int, raw: str) -> GarageSpeechWhitelist:
        user = await _resolve_user(session, raw)
        result = await session.execute(
            select(GarageSpeechWhitelist).where(
                GarageSpeechWhitelist.chat_id == chat_id,
                GarageSpeechWhitelist.user_id == user.id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = GarageSpeechWhitelist(chat_id=chat_id, user_id=user.id, created_by_user_id=operator_user_id)
            session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def remove_whitelist(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(GarageSpeechWhitelist).where(
                GarageSpeechWhitelist.chat_id == chat_id,
                GarageSpeechWhitelist.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        await session.delete(item)
        await session.flush()
        return True

    @staticmethod
    async def is_certified_teacher(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(GarageCertifiedTeacher.id).where(
                GarageCertifiedTeacher.chat_id == chat_id,
                GarageCertifiedTeacher.user_id == user_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def is_whitelisted(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(GarageSpeechWhitelist.id).where(
                GarageSpeechWhitelist.chat_id == chat_id,
                GarageSpeechWhitelist.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None


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
    async def list_open_course_teachers(session: AsyncSession, chat_id: int) -> list[tuple[TeacherProfile, TgUser | None]]:
        result = await session.execute(
            select(TeacherProfile, TgUser)
            .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
            .where(TeacherProfile.chat_id == chat_id, TeacherProfile.open_course_today.is_(True))
            .order_by(TeacherProfile.updated_at.desc())
        )
        return list(result.all())

    @staticmethod
    async def get_member_location(session: AsyncSession, chat_id: int, user_id: int) -> MemberLocation | None:
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
        rows = await TeacherSearchService.list_open_course_teachers(session, chat_id) if only_open_course else list(
            (
                await session.execute(
                    select(TeacherProfile, TgUser)
                    .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
                    .where(TeacherProfile.chat_id == chat_id)
                    .order_by(TeacherProfile.updated_at.desc())
                )
            ).all()
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
        rows = await TeacherSearchService.list_open_course_teachers(session, chat_id) if only_open_course else list(
            (
                await session.execute(
                    select(TeacherProfile, TgUser)
                    .join(TgUser, TgUser.id == TeacherProfile.user_id, isouter=True)
                    .where(TeacherProfile.chat_id == chat_id)
                    .order_by(TeacherProfile.updated_at.desc())
                )
            ).all()
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
            item = TeacherDailyAttendance(chat_id=chat_id, user_id=user_id, biz_date=today, source_message_id=source_message_id)
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


class CarReviewService:
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
        for field_key, field_label in CarReviewService.DEFAULT_FIELDS:
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
        setting = await CarReviewService.ensure_setting(session, chat_id)
        await CarReviewService.ensure_default_fields(session, chat_id)
        return setting

    @staticmethod
    async def update_setting(session: AsyncSession, chat_id: int, **updates) -> CarReviewSetting:
        setting = await CarReviewService.get_setting(session, chat_id)
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
        await CarReviewService.ensure_default_fields(session, chat_id)
        result = await session.execute(
            select(CarReviewCustomField)
            .where(CarReviewCustomField.chat_id == chat_id)
            .order_by(CarReviewCustomField.sort_order.asc(), CarReviewCustomField.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_recent_reports(session: AsyncSession, chat_id: int, limit: int = 20) -> list[CarReviewReport]:
        result = await session.execute(
            select(CarReviewReport)
            .where(CarReviewReport.chat_id == chat_id)
            .order_by(CarReviewReport.report_id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_report(
        session: AsyncSession,
        *,
        chat_id: int,
        teacher_user_id: int,
        author_user_id: int,
        review_text: str,
        media_file_ids: list[str] | None = None,
        scores: dict | None = None,
    ) -> CarReviewReport:
        report = CarReviewReport(
            chat_id=chat_id,
            teacher_user_id=teacher_user_id,
            author_user_id=author_user_id,
            review_text=review_text,
            process_text=review_text,
            media_file_ids=media_file_ids or [],
            scores=scores or {},
            report_status="pending",
        )
        session.add(report)
        await session.flush()
        await CarReviewService.append_audit(
            session,
            chat_id=chat_id,
            report_id=report.report_id,
            action="submitted",
            operator_user_id=author_user_id,
            payload={"review_text": review_text},
        )
        return report

    @staticmethod
    async def append_audit(
        session: AsyncSession,
        *,
        chat_id: int,
        report_id: int | None,
        action: str,
        operator_user_id: int | None,
        payload: dict | None = None,
    ) -> CarReviewAuditLog:
        item = CarReviewAuditLog(
            chat_id=chat_id,
            report_id=report_id,
            action=action,
            operator_user_id=operator_user_id,
            payload=payload or {},
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def approve_report(
        session: AsyncSession,
        *,
        chat_id: int,
        report_id: int,
        approver_user_id: int,
    ) -> CarReviewReport | None:
        report = await session.get(CarReviewReport, report_id)
        if report is None or report.chat_id != chat_id:
            return None
        report.report_status = "approved"
        report.approved_by_user_id = approver_user_id
        report.approved_at = dt.datetime.now(dt.UTC)
        report.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        await CarReviewService.append_audit(
            session,
            chat_id=chat_id,
            report_id=report_id,
            action="approved",
            operator_user_id=approver_user_id,
            payload={},
        )
        return report

    @staticmethod
    async def list_rankings(
        session: AsyncSession,
        chat_id: int,
        *,
        limit: int = 10,
    ) -> list[dict]:
        result = await session.execute(
            select(CarReviewReport, TgUser)
            .join(TgUser, TgUser.id == CarReviewReport.teacher_user_id, isouter=True)
            .where(
                CarReviewReport.chat_id == chat_id,
                CarReviewReport.report_status.in_(["approved", "published"]),
            )
            .order_by(CarReviewReport.report_id.desc())
        )
        agg: dict[int, dict] = {}
        for report, user in result.all():
            if report.teacher_user_id is None:
                continue
            item = agg.setdefault(
                report.teacher_user_id,
                {
                    "teacher_user_id": report.teacher_user_id,
                    "display_name": build_user_display_name(user, report.teacher_user_id) if user else f"用户{report.teacher_user_id}",
                    "count": 0,
                    "score_total": 0.0,
                },
            )
            item["count"] += 1
            score_value = (report.scores or {}).get("total_score")
            if isinstance(score_value, (int, float)):
                item["score_total"] += float(score_value)
        rows = []
        for item in agg.values():
            avg = item["score_total"] / item["count"] if item["count"] else 0.0
            rows.append({**item, "avg_score": round(avg, 2)})
        rows.sort(key=lambda item: (-item["avg_score"], -item["count"], item["teacher_user_id"]))
        return rows[:limit]
