from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.features.garage.services.garage_auth_service import GarageAuthService
from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import (
    CarReviewAuditLog,
    CarReviewReport,
    TeacherProfile,
)


class CarReviewReportMixin:
    @staticmethod
    async def list_recent_reports(session: AsyncSession, chat_id: int, limit: int = 20) -> list[CarReviewReport]:
        return await CarReviewReportMixin.list_reports(session, chat_id, limit=limit)

    @staticmethod
    async def list_reports(
        session: AsyncSession,
        chat_id: int,
        *,
        status: str = "all",
        limit: int = 20,
    ) -> list[CarReviewReport]:
        stmt = select(CarReviewReport).where(CarReviewReport.chat_id == chat_id)
        if status and status != "all":
            stmt = stmt.where(CarReviewReport.report_status == status)
        result = await session.execute(stmt.order_by(CarReviewReport.report_id.desc()).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def list_reports_for_teacher(
        session: AsyncSession,
        chat_id: int,
        teacher_user_id: int,
        *,
        limit: int = 5,
    ) -> list[tuple[CarReviewReport, TgUser | None]]:
        author = aliased(TgUser)
        result = await session.execute(
            select(CarReviewReport, author)
            .join(author, author.id == CarReviewReport.author_user_id, isouter=True)
            .where(
                CarReviewReport.chat_id == chat_id,
                CarReviewReport.teacher_user_id == teacher_user_id,
                CarReviewReport.report_status.in_(["approved", "published"]),
            )
            .order_by(CarReviewReport.created_at.desc(), CarReviewReport.report_id.desc())
            .limit(limit)
        )
        return list(result.all())

    @staticmethod
    async def count_reports_by_status(session: AsyncSession, chat_id: int) -> dict[str, int]:
        result = await session.execute(
            select(CarReviewReport.report_status, func.count(CarReviewReport.report_id))
            .where(CarReviewReport.chat_id == chat_id)
            .group_by(CarReviewReport.report_status)
        )
        stats: dict[str, int] = {"all": 0, "pending": 0, "approved": 0, "published": 0, "rejected": 0}
        for status, count in result.all():
            stats[str(status or "")] = int(count or 0)
        stats["all"] = sum(v for k, v in stats.items() if k != "all")
        return stats

    @staticmethod
    async def get_report(session: AsyncSession, chat_id: int, report_id: int) -> CarReviewReport | None:
        result = await session.execute(
            select(CarReviewReport).where(CarReviewReport.chat_id == chat_id, CarReviewReport.report_id == report_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_audit_logs(
        session: AsyncSession,
        *,
        chat_id: int,
        report_id: int,
        limit: int = 20,
    ) -> list[CarReviewAuditLog]:
        result = await session.execute(
            select(CarReviewAuditLog)
            .where(CarReviewAuditLog.chat_id == chat_id, CarReviewAuditLog.report_id == report_id)
            .order_by(CarReviewAuditLog.id.desc())
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
        process_text: str | None = None,
    ) -> CarReviewReport:
        report = CarReviewReport(
            chat_id=chat_id,
            teacher_user_id=teacher_user_id,
            author_user_id=author_user_id,
            review_text=review_text,
            process_text=process_text if process_text is not None else review_text,
            media_file_ids=media_file_ids or [],
            scores=scores or {},
            report_status="pending",
        )
        session.add(report)
        await session.flush()
        await CarReviewReportMixin.append_audit(
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
    async def has_audit_action(session: AsyncSession, *, chat_id: int, report_id: int, action: str) -> bool:
        result = await session.execute(
            select(CarReviewAuditLog.id)
            .where(
                CarReviewAuditLog.chat_id == chat_id,
                CarReviewAuditLog.report_id == report_id,
                CarReviewAuditLog.action == action,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

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
        await CarReviewReportMixin.append_audit(
            session,
            chat_id=chat_id,
            report_id=report_id,
            action="approved",
            operator_user_id=approver_user_id,
            payload={},
        )
        return report

    @staticmethod
    async def reject_report(
        session: AsyncSession,
        *,
        chat_id: int,
        report_id: int,
        operator_user_id: int,
        reason: str | None = None,
    ) -> CarReviewReport | None:
        report = await CarReviewReportMixin.get_report(session, chat_id, report_id)
        if report is None:
            return None
        report.report_status = "rejected"
        report.approved_by_user_id = operator_user_id
        report.approved_at = dt.datetime.now(dt.UTC)
        report.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        await CarReviewReportMixin.append_audit(
            session,
            chat_id=chat_id,
            report_id=report_id,
            action="rejected",
            operator_user_id=operator_user_id,
            payload={"reason": reason or ""},
        )
        return report

    @staticmethod
    async def list_rankings(
        session: AsyncSession,
        chat_id: int,
        *,
        limit: int = 10,
        since: dt.datetime | None = None,
    ) -> list[dict]:
        stmt = (
            select(CarReviewReport, TgUser)
            .join(TgUser, TgUser.id == CarReviewReport.teacher_user_id, isouter=True)
            .where(CarReviewReport.chat_id == chat_id, CarReviewReport.report_status.in_(["approved", "published"]))
        )
        if since is not None:
            stmt = stmt.where(CarReviewReport.created_at >= since)
        result = await session.execute(stmt.order_by(CarReviewReport.report_id.desc()))
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
                    "score_count": 0,
                },
            )
            item["count"] += 1
            score_value = (report.scores or {}).get("total_score")
            if isinstance(score_value, (int, float)):
                item["score_total"] += float(score_value)
                item["score_count"] += 1
        rows = []
        for item in agg.values():
            avg = item["score_total"] / item["score_count"] if item["score_count"] else 0.0
            rows.append({**item, "avg_score": round(avg, 2)})
        rows.sort(key=lambda item: (-item["avg_score"], -item["count"], item["teacher_user_id"]))
        return rows[:limit]

    @staticmethod
    async def get_teacher_review_stats(
        session: AsyncSession,
        chat_id: int,
        teacher_user_id: int,
    ) -> dict[str, float | int]:
        result = await session.execute(
            select(CarReviewReport)
            .where(
                CarReviewReport.chat_id == chat_id,
                CarReviewReport.teacher_user_id == teacher_user_id,
                CarReviewReport.report_status.in_(["approved", "published"]),
            )
            .order_by(CarReviewReport.report_id.desc())
        )
        reports = list(result.scalars().all())
        score_total = 0.0
        score_count = 0
        for report in reports:
            score_value = (report.scores or {}).get("total_score")
            if isinstance(score_value, (int, float)):
                score_total += float(score_value)
                score_count += 1
        count = len(reports)
        avg = score_total / score_count if score_count else 0.0
        return {"count": count, "avg_score": round(avg, 2)}

    @staticmethod
    async def refresh_teacher_board_info(
        session: AsyncSession,
        chat_id: int,
        teacher_user_id: int,
    ) -> dict[str, float | int]:
        stats = await CarReviewReportMixin.get_teacher_review_stats(session, chat_id, teacher_user_id)
        result = await session.execute(
            select(TeacherProfile).where(
                TeacherProfile.chat_id == chat_id,
                TeacherProfile.user_id == teacher_user_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = TeacherProfile(chat_id=chat_id, user_id=teacher_user_id)
            session.add(profile)

        labels = [
            label
            for label in list(profile.labels or [])
            if not (isinstance(label, str) and (label.startswith("车评") or label.startswith("均分")))
        ]
        count = int(stats["count"])
        if count > 0:
            avg_text = f"{float(stats['avg_score']):g}"
            labels.extend([f"车评{count}条", f"均分{avg_text}"])
        profile.labels = labels
        profile.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return stats

    @staticmethod
    async def find_lookup_teacher_by_username(
        session: AsyncSession,
        chat_id: int,
        username: str,
    ) -> TgUser | None:
        normalized = _normalize_lookup_username(username)
        if not normalized:
            return None
        result = await session.execute(
            select(TgUser)
            .join(
                TeacherProfile,
                and_(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == TgUser.id),
            )
            .where(
                func.lower(TgUser.username) == normalized,
            )
            .limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        if not await GarageAuthService.has_effective_teacher_profile(session, chat_id, user.id):
            return None
        return user

    @staticmethod
    async def list_lookup_teachers(
        session: AsyncSession,
        chat_id: int,
        *,
        limit: int = 200,
    ) -> list[TgUser]:
        result = await session.execute(
            select(TgUser)
            .join(
                TeacherProfile,
                and_(TeacherProfile.chat_id == chat_id, TeacherProfile.user_id == TgUser.id),
            )
            .where(TgUser.username.is_not(None))
            .order_by(TgUser.username.asc())
            .limit(limit)
        )
        users = list(result.scalars().all())
        filtered: list[TgUser] = []
        for user in users:
            if await GarageAuthService.has_effective_teacher_profile(session, chat_id, user.id):
                filtered.append(user)
        return filtered


def _normalize_lookup_username(value: str) -> str:
    username = (value or "").strip()
    if username.startswith("@"):
        username = username[1:]
    return username.lower()
