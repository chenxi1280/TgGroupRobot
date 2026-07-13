from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from sqlalchemy import and_, select

from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import (
    GarageCertifiedTeacher,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
)
from backend.shared.time_helper import LOCAL_TIMEZONE

_SUMMARY_ROW_FIELDS = 4


def _attendance_status_label(status: str | None) -> str:
    return {"open": "开课中", "full": "满课", "rest": "休息"}.get(
        status, "未开课"
    )


async def _attendance_chat_id(session, chat_id: int) -> int:
    setting = await session.get(TeacherSearchSetting, chat_id)
    uses_external = (
        setting is not None and setting.attendance_mode == "external"
        and setting.attendance_source_chat_id is not None
    )
    return int(setting.attendance_source_chat_id) if uses_external else chat_id


async def _load_summary_rows(
    session, *, chat_id: int, pool_chat_id: int, attendance_chat_id: int
) -> list[tuple]:
    today = dt.datetime.now(dt.UTC).astimezone(LOCAL_TIMEZONE).date()
    statement = (
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
    result = await session.execute(statement)
    return [tuple(row) if len(row) >= _SUMMARY_ROW_FIELDS else (*row, None) for row in result.all()]


def _filter_open_teachers(rows: list[tuple], *, only_open: bool) -> list[tuple]:
    if not only_open:
        return rows
    return [
        row for row in rows
        if row[3] is not None and row[3].status in {"open", "full"}
    ]


def _teacher_group_key(profile, *, partition_by: str) -> str:
    if partition_by == "price":
        return (profile.price_text if profile else None) or "未分价位"
    return (profile.region_text if profile else None) or "未分地区"


def _profile_is_empty(profile) -> bool:
    if profile is None:
        return True
    return not bool(
        (profile.region_text or "").strip()
        or (profile.price_text or "").strip()
        or (profile.labels or [])
    )


def _profile_partition_extras(profile, *, partition_by: str) -> list[str]:
    extras: list[str] = []
    if partition_by != "price" and profile and profile.price_text:
        extras.append(profile.price_text)
    if partition_by != "region" and profile and profile.region_text:
        extras.append(profile.region_text)
    labels = " / ".join((profile.labels or [])[:3]) if profile else ""
    if labels:
        extras.append(labels)
    return extras


def _profile_health_extras(profile) -> list[str]:
    extras = []
    if _profile_is_empty(profile):
        extras.append("资料待完善")
    if (
        profile is None or getattr(profile, "latitude", None) is None
        or getattr(profile, "longitude", None) is None
    ):
        extras.append("未定位")
    return extras


def _teacher_extras(profile, attendance, *, partition_by: str) -> list[str]:
    return [
        *_profile_partition_extras(profile, partition_by=partition_by),
        _attendance_status_label(getattr(attendance, "status", None)),
        *_profile_health_extras(profile),
    ]


def _group_teacher_rows(rows: list[tuple], *, partition_by: str, badge: str):
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for teacher, profile, user, attendance in rows:
        key = _teacher_group_key(profile, partition_by=partition_by)
        display_name = (
            build_user_display_name(user, teacher.user_id)
            if user else f"用户{teacher.user_id}"
        )
        extras = _teacher_extras(profile, attendance, partition_by=partition_by)
        suffix = f"（{' | '.join(extras)}）" if extras else ""
        groups.setdefault(key, []).append(f"{badge} {display_name}{suffix}")
    return groups


def _render_teacher_groups(groups, *, partition_by: str, only_open: bool) -> str:
    count = sum(len(members) for members in groups.values())
    partition_label = "价格" if partition_by == "price" else "地区"
    lines = [
        "🧾 老师汇总信息", "", f"分区方式：按{partition_label}",
        f"只显开课：{'是' if only_open else '否'}", f"老师数量：{count}",
    ]
    for key, members in groups.items():
        lines.extend(["", f"【{key}】({len(members)}人)"])
        lines.extend(
            f"{index}. {member}" for index, member in enumerate(members, start=1)
        )
    return "\n".join(lines)


async def build_teacher_summary(session, chat_id: int, *, service) -> str:
    settings = await service.get_settings(session, chat_id)
    pool_chat_id = await service._get_teacher_pool_chat_id(session, chat_id)
    attendance_chat_id = await _attendance_chat_id(session, chat_id)
    rows = await _load_summary_rows(
        session, chat_id=chat_id, pool_chat_id=pool_chat_id,
        attendance_chat_id=attendance_chat_id,
    )
    rows = _filter_open_teachers(
        rows, only_open=settings.garage_summary_only_open_course
    )
    if not rows:
        return (
            "🧾 老师汇总信息\n\n当前没有符合条件的认证老师。\n"
            "你可以先添加认证老师，或关闭“只显开课”后再试。"
        )
    partition_by = settings.garage_summary_partition_by or "region"
    groups = _group_teacher_rows(
        rows, partition_by=partition_by,
        badge=getattr(settings, "garage_auth_badge", "🤝") or "🤝",
    )
    return _render_teacher_groups(
        groups, partition_by=partition_by,
        only_open=settings.garage_summary_only_open_course,
    )
