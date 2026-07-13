from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import ChatSettings, TgChat, TgUser
from backend.platform.db.schema.models.garage_features import (
    GarageCertifiedTeacher,
    GarageSpeechWhitelist,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
)
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.time_helper import LOCAL_TIMEZONE


@dataclass(frozen=True)
class TeacherPoolInfo:
    requested_chat_id: int
    pool_chat_id: int
    pool_title: str
    shared_via_alliance: bool

    @property
    def display_text(self) -> str:
        if self.shared_via_alliance:
            return f"联盟共享认证池（来自：{self.pool_title}）"
        return "本群认证池"


def _teacher_attendance_status_label(status: str | None) -> str:
    return {
        "open": "开课中",
        "full": "满课",
        "rest": "休息",
    }.get(status, "未开课")


class GarageAuthService:
    @staticmethod
    async def _get_teacher_pool_chat_id(session: AsyncSession, chat_id: int) -> int:
        from backend.features.garage.services.alliance_service import AllianceService

        alliance = await AllianceService.get_alliance_by_chat(session, chat_id)
        if alliance is not None and alliance.owner_chat_id:
            return int(alliance.owner_chat_id)
        return chat_id

    @staticmethod
    async def _list_certified_teachers_for_chat(
        session: AsyncSession,
        storage_chat_id: int,
    ) -> list[tuple[GarageCertifiedTeacher, TgUser | None]]:
        result = await session.execute(
            select(GarageCertifiedTeacher, TgUser)
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .where(GarageCertifiedTeacher.chat_id == storage_chat_id)
            .order_by(GarageCertifiedTeacher.id.asc())
        )
        return list(result.all())

    @staticmethod
    async def _list_enabled_teacher_rows_for_chat(
        session: AsyncSession,
        storage_chat_id: int,
    ) -> list[GarageCertifiedTeacher]:
        result = await session.execute(
            select(GarageCertifiedTeacher)
            .where(
                GarageCertifiedTeacher.chat_id == storage_chat_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
            .order_by(GarageCertifiedTeacher.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _upsert_teacher_for_chat(
        session: AsyncSession,
        storage_chat_id: int,
        user_id: int,
        *, operator_user_id: int | None,
    ) -> GarageCertifiedTeacher:
        result = await session.execute(
            select(GarageCertifiedTeacher).where(
                GarageCertifiedTeacher.chat_id == storage_chat_id,
                GarageCertifiedTeacher.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = GarageCertifiedTeacher(
                chat_id=storage_chat_id,
                user_id=user_id,
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
    async def _remove_teacher_for_chat(session: AsyncSession, storage_chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(GarageCertifiedTeacher).where(
                GarageCertifiedTeacher.chat_id == storage_chat_id,
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
    async def get_teacher_pool_info(session: AsyncSession, chat_id: int) -> TeacherPoolInfo:
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        pool_chat = await session.get(TgChat, pool_chat_id)
        return TeacherPoolInfo(
            requested_chat_id=chat_id,
            pool_chat_id=pool_chat_id,
            pool_title=(pool_chat.title or str(pool_chat_id)) if pool_chat is not None else str(pool_chat_id),
            shared_via_alliance=pool_chat_id != chat_id,
        )

    @staticmethod
    async def resolve_teacher_pool_chat_id(session: AsyncSession, chat_id: int) -> int:
        return await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)

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
    async def list_certified_teachers(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[GarageCertifiedTeacher, TgUser | None]]:
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        return await GarageAuthService._list_certified_teachers_for_chat(session, pool_chat_id)

    @staticmethod
    async def list_effective_certified_teachers(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[GarageCertifiedTeacher, TgUser | None]]:
        return await GarageAuthService.list_certified_teachers(session, chat_id)

    @staticmethod
    async def add_teacher(
        session: AsyncSession,
        chat_id: int,
        operator_user_id: int,
        *, raw: str,
    ) -> GarageCertifiedTeacher:
        user = await _resolve_user(session, raw)
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        return await GarageAuthService._upsert_teacher_for_chat(session, pool_chat_id, user.id, operator_user_id=operator_user_id)

    @staticmethod
    async def add_teacher_by_user_id(
        session: AsyncSession,
        chat_id: int,
        user_id: int,
        *, operator_user_id: int | None,
    ) -> GarageCertifiedTeacher:
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        return await GarageAuthService._upsert_teacher_for_chat(session, pool_chat_id, user_id, operator_user_id=operator_user_id)

    @staticmethod
    async def remove_teacher(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        return await GarageAuthService._remove_teacher_for_chat(session, pool_chat_id, user_id)

    @staticmethod
    async def merge_local_certified_teachers_into_pool(
        session: AsyncSession,
        *,
        source_chat_id: int,
        pool_chat_id: int,
        operator_user_id: int | None,
    ) -> int:
        rows = await GarageAuthService._list_enabled_teacher_rows_for_chat(session, source_chat_id)
        merged_count = 0
        for row in rows:
            await GarageAuthService._upsert_teacher_for_chat(
                session,
                pool_chat_id,
                row.user_id,
                operator_user_id=row.certified_by_user_id or operator_user_id,
            )
            merged_count += 1
        return merged_count

    @staticmethod
    async def sync_local_certified_teachers_from_effective_pool(
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int | None,
    ) -> int:
        effective_rows = await GarageAuthService.list_effective_certified_teachers(session, chat_id)
        local_rows = await GarageAuthService._list_enabled_teacher_rows_for_chat(session, chat_id)
        effective_user_ids = {row.user_id for row, _ in effective_rows}
        local_user_ids = {row.user_id for row in local_rows}

        for row, _ in effective_rows:
            await GarageAuthService._upsert_teacher_for_chat(
                session,
                chat_id,
                row.user_id,
                operator_user_id=row.certified_by_user_id or operator_user_id,
            )
        for row in local_rows:
            if row.user_id not in effective_user_ids:
                await session.delete(row)
        await session.flush()
        return len(effective_user_ids - local_user_ids) + len(local_user_ids - effective_user_ids)

    @staticmethod
    async def list_whitelist(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[GarageSpeechWhitelist, TgUser | None]]:
        result = await session.execute(
            select(GarageSpeechWhitelist, TgUser)
            .join(TgUser, TgUser.id == GarageSpeechWhitelist.user_id, isouter=True)
            .where(GarageSpeechWhitelist.chat_id == chat_id)
            .order_by(GarageSpeechWhitelist.id.asc())
        )
        return list(result.all())

    @staticmethod
    async def add_whitelist(
        session: AsyncSession,
        chat_id: int,
        operator_user_id: int,
        *, raw: str,
    ) -> GarageSpeechWhitelist:
        user = await _resolve_user(session, raw)
        result = await session.execute(
            select(GarageSpeechWhitelist).where(
                GarageSpeechWhitelist.chat_id == chat_id,
                GarageSpeechWhitelist.user_id == user.id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = GarageSpeechWhitelist(
                chat_id=chat_id,
                user_id=user.id,
                created_by_user_id=operator_user_id,
            )
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
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        result = await session.execute(
            select(GarageCertifiedTeacher.id).where(
                GarageCertifiedTeacher.chat_id == pool_chat_id,
                GarageCertifiedTeacher.user_id == user_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def is_effective_certified_teacher(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        return await GarageAuthService.is_certified_teacher(session, chat_id, user_id)

    @staticmethod
    async def has_effective_teacher_profile(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        if not await GarageAuthService.is_effective_certified_teacher(session, chat_id, user_id):
            return False
        result = await session.execute(
            select(TeacherProfile.id).where(
                TeacherProfile.chat_id == chat_id,
                TeacherProfile.user_id == user_id,
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

    @staticmethod
    async def build_teacher_summary(session: AsyncSession, chat_id: int) -> str:
        settings = await GarageAuthService.get_settings(session, chat_id)
        pool_chat_id = await GarageAuthService._get_teacher_pool_chat_id(session, chat_id)
        attendance_chat_id = chat_id
        teacher_search_setting = await session.get(TeacherSearchSetting, chat_id)
        if (
            teacher_search_setting is not None
            and teacher_search_setting.attendance_mode == "external"
            and teacher_search_setting.attendance_source_chat_id is not None
        ):
            attendance_chat_id = int(teacher_search_setting.attendance_source_chat_id)
        today = dt.datetime.now(dt.UTC).astimezone(LOCAL_TIMEZONE).date()
        result = await session.execute(
            select(GarageCertifiedTeacher, TeacherProfile, TgUser, TeacherDailyAttendance)
            .join(
                TeacherProfile,
                and_(
                    TeacherProfile.chat_id == chat_id,
                    TeacherProfile.user_id == GarageCertifiedTeacher.user_id,
                ),
                isouter=True,
            )
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .join(
                TeacherDailyAttendance,
                and_(
                    TeacherDailyAttendance.chat_id == attendance_chat_id,
                    TeacherDailyAttendance.user_id == GarageCertifiedTeacher.user_id,
                    TeacherDailyAttendance.biz_date == today,
                ),
                isouter=True,
            )
            .where(
                GarageCertifiedTeacher.chat_id == pool_chat_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
            .order_by(GarageCertifiedTeacher.created_at.asc(), GarageCertifiedTeacher.id.asc())
        )
        rows = []
        for row in result.all():
            if len(row) >= 4:
                rows.append(row)
            else:
                teacher, profile, user = row
                rows.append((teacher, profile, user, None))

        if settings.garage_summary_only_open_course:
            rows = [
                row
                for row in rows
                if row[3] is not None and row[3].status in {"open", "full"}
            ]

        if not rows:
            return (
                "🧾 老师汇总信息\n\n"
                "当前没有符合条件的认证老师。\n"
                "你可以先添加认证老师，或关闭“只显开课”后再试。"
            )

        partition_by = settings.garage_summary_partition_by or "region"
        badge = getattr(settings, "garage_auth_badge", "🤝") or "🤝"
        groups: OrderedDict[str, list[str]] = OrderedDict()
        total_count = 0

        for teacher, profile, user, attendance in rows:
            if partition_by == "price":
                key = (profile.price_text if profile else None) or "未分价位"
            else:
                key = (profile.region_text if profile else None) or "未分地区"

            display_name = (
                build_user_display_name(user, teacher.user_id) if user else f"用户{teacher.user_id}"
            )
            labels = " / ".join((profile.labels or [])[:3]) if profile and profile.labels else ""
            extras: list[str] = []
            if partition_by != "price" and profile and profile.price_text:
                extras.append(profile.price_text)
            if partition_by != "region" and profile and profile.region_text:
                extras.append(profile.region_text)
            if labels:
                extras.append(labels)
            status = getattr(attendance, "status", None)
            extras.append(_teacher_attendance_status_label(status))
            if profile is None or not (
                (profile.region_text or "").strip()
                or (profile.price_text or "").strip()
                or (profile.labels or [])
            ):
                extras.append("资料待完善")
            if (
                profile is None
                or getattr(profile, "latitude", None) is None
                or getattr(profile, "longitude", None) is None
            ):
                extras.append("未定位")

            line = f"{badge} {display_name}"
            if extras:
                line += f"（{' | '.join(extras)}）"

            groups.setdefault(key, []).append(line)
            total_count += 1

        partition_label = "价格" if partition_by == "price" else "地区"
        lines = [
            "🧾 老师汇总信息",
            "",
            f"分区方式：按{partition_label}",
            f"只显开课：{'是' if settings.garage_summary_only_open_course else '否'}",
            f"老师数量：{total_count}",
        ]

        for key, members in groups.items():
            lines.append("")
            lines.append(f"【{key}】({len(members)}人)")
            lines.extend(f"{idx}. {member}" for idx, member in enumerate(members, start=1))

        return "\n".join(lines)

    @staticmethod
    async def list_teacher_self_service_chats(
        session: AsyncSession,
        user_id: int,
    ) -> list[tuple[TgChat, TeacherPoolInfo]]:
        result = await session.execute(
            select(TgChat)
            .where(TgChat.type.in_(["group", "supergroup"]))
            .order_by(TgChat.updated_at.desc(), TgChat.id.desc())
        )
        chats = list(result.scalars().all())
        items: list[tuple[TgChat, TeacherPoolInfo]] = []
        for chat in chats:
            if await GarageAuthService.is_effective_certified_teacher(session, chat.id, user_id):
                items.append((chat, await GarageAuthService.get_teacher_pool_info(session, chat.id)))
        items.sort(key=lambda item: (item[0].title or "", item[0].id))
        return items
