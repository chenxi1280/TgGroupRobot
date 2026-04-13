from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import ChatSettings, TgUser
from backend.platform.db.schema.models.garage_features import (
    GarageCertifiedTeacher,
    GarageSpeechWhitelist,
    TeacherProfile,
)
from backend.shared.services.chat_service import get_chat_settings


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
    async def list_certified_teachers(
        session: AsyncSession,
        chat_id: int,
    ) -> list[tuple[GarageCertifiedTeacher, TgUser | None]]:
        result = await session.execute(
            select(GarageCertifiedTeacher, TgUser)
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .where(GarageCertifiedTeacher.chat_id == chat_id)
            .order_by(GarageCertifiedTeacher.id.asc())
        )
        return list(result.all())

    @staticmethod
    async def add_teacher(
        session: AsyncSession,
        chat_id: int,
        operator_user_id: int,
        raw: str,
    ) -> GarageCertifiedTeacher:
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
        raw: str,
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

    @staticmethod
    async def build_teacher_summary(session: AsyncSession, chat_id: int) -> str:
        settings = await GarageAuthService.get_settings(session, chat_id)
        result = await session.execute(
            select(GarageCertifiedTeacher, TeacherProfile, TgUser)
            .join(
                TeacherProfile,
                and_(
                    TeacherProfile.chat_id == GarageCertifiedTeacher.chat_id,
                    TeacherProfile.user_id == GarageCertifiedTeacher.user_id,
                ),
                isouter=True,
            )
            .join(TgUser, TgUser.id == GarageCertifiedTeacher.user_id, isouter=True)
            .where(
                GarageCertifiedTeacher.chat_id == chat_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
            .order_by(GarageCertifiedTeacher.created_at.asc(), GarageCertifiedTeacher.id.asc())
        )
        rows = list(result.all())

        if settings.garage_summary_only_open_course:
            rows = [row for row in rows if row[1] is not None and bool(row[1].open_course_today)]

        if not rows:
            return (
                "🧾 老师汇总信息\n\n"
                "当前没有符合条件的认证老师。\n"
                "你可以先添加认证老师，或关闭“只显开课”后再试。"
            )

        partition_by = settings.garage_summary_partition_by or "region"
        groups: OrderedDict[str, list[str]] = OrderedDict()
        total_count = 0

        for teacher, profile, user in rows:
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
            if profile and profile.open_course_today:
                extras.append("开课中")

            line = display_name
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
