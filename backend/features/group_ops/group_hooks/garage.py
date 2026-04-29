from __future__ import annotations

from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import (
    CarReviewService,
    GarageAuthService,
    TeacherSearchService,
)
from backend.platform.db.runtime.session import Database

from .car_review import _process_car_review_features, _publish_car_review_report
from .garage_limit import _garage_limit_hits_message, _process_garage_limit
from .teacher_search import _process_teacher_search_features


async def _process_garage_features(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
    settings,
    is_admin: bool,
) -> bool:
    text = (message_text or "").strip()
    async with db.session_factory() as session:
        teacher_setting = await TeacherSearchService.get_setting(session, chat.id)
        car_review_setting = await CarReviewService.get_setting(session, chat.id)
        is_teacher = await GarageAuthService.is_certified_teacher(session, chat.id, user.id)
        is_attendance_teacher = is_teacher
        if not is_attendance_teacher and getattr(teacher_setting, "attendance_enabled", False):
            is_attendance_teacher = await TeacherSearchService.is_certified_teacher_for_attendance_source(
                session,
                chat.id,
                user.id,
            )
        is_whitelisted = await GarageAuthService.is_whitelisted(session, chat.id, user.id)

        if await _process_garage_limit(
            context,
            session,
            chat,
            user,
            message,
            text,
            settings,
            is_admin=is_admin,
            is_teacher=is_teacher,
            is_whitelisted=is_whitelisted,
        ):
            return True

        if await _process_teacher_search_features(
            context,
            session,
            chat,
            user,
            message,
            text,
            teacher_setting,
            is_teacher=is_teacher,
            is_attendance_teacher=is_attendance_teacher,
            is_admin=is_admin,
            is_whitelisted=is_whitelisted,
        ):
            return True

        if await _process_car_review_features(
            context,
            session,
            chat,
            user,
            message,
            text,
            car_review_setting,
        ):
            return True

        if (
            getattr(settings, "garage_auth_enabled", False)
            and is_teacher
            and text
            and not text.startswith("/")
        ):
            from backend.features.nearby.services.nearby_profile_service import build_user_display_name
            from backend.shared.services.publish_service import PublishService

            badge = getattr(settings, "garage_auth_badge", "🤝") or "🤝"
            display_name = build_user_display_name(user, user.id)
            await session.commit()
            await PublishService.send_temporary(
                context,
                chat_id=chat.id,
                text=f"{badge} 认证老师 {display_name}",
                delete_after_seconds=8,
                reply_to_message_id=message.message_id,
            )
            return False

        await session.commit()
    return False


__all__ = [
    "_garage_limit_hits_message",
    "_process_garage_features",
    "_publish_car_review_report",
]
