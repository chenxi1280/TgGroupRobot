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

        await session.commit()
    return False


__all__ = [
    "_garage_limit_hits_message",
    "_process_garage_features",
    "_publish_car_review_report",
]
