from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database

log = structlog.get_logger(__name__)

RESERVED_GROUP_TEXT_COMMANDS = frozenset({"签到", "积分", "积分排行"})


def is_reserved_group_text_command(text: str) -> bool:
    return text.strip() in RESERVED_GROUP_TEXT_COMMANDS


async def get_reserved_group_text_commands(session, chat_id: int) -> set[str]:
    from backend.shared.services.chat_service import get_chat_settings

    commands = set(RESERVED_GROUP_TEXT_COMMANDS)
    settings = await get_chat_settings(session, chat_id)
    for attr in ("points_alias", "points_rank_alias"):
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            commands.add(value)
    return commands


async def is_reserved_group_text_command_for_chat(session, chat_id: int, text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if normalized in RESERVED_GROUP_TEXT_COMMANDS:
        return True
    return normalized in await get_reserved_group_text_commands(session, chat_id)


async def _try_points_text_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    from backend.features.points.points_handler import points_text_trigger_handler

    return await points_text_trigger_handler(update, context, payload)


async def _try_teacher_search_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    if update.effective_chat.id != chat_id:
        return False
    if update.effective_chat.type not in {"group", "supergroup"}:
        return False

    from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchService
    from backend.features.group_ops.group_hooks.teacher_search import _process_teacher_search_features
    from backend.shared.services.permission_service import is_user_admin

    db: Database = context.application.bot_data["db"]
    try:
        is_admin = await is_user_admin(context, chat_id, update.effective_user.id)
    except Exception as exc:
        log.warning(
            "text_trigger_admin_check_failed",
            chat_id=chat_id,
            user_id=update.effective_user.id,
            error=str(exc),
        )
        is_admin = False

    async with db.session_factory() as session:
        teacher_setting = await TeacherSearchService.get_setting(session, chat_id)
        is_teacher = await GarageAuthService.is_certified_teacher(session, chat_id, update.effective_user.id)
        is_whitelisted = await GarageAuthService.is_whitelisted(session, chat_id, update.effective_user.id)
        return await _process_teacher_search_features(
            context,
            session,
            update.effective_chat,
            update.effective_user,
            update.effective_message,
            payload,
            teacher_setting,
            is_teacher=is_teacher,
            is_admin=is_admin,
            is_whitelisted=is_whitelisted,
        )


async def try_group_text_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    trigger_text = payload.strip()
    if not trigger_text:
        return False

    handled = await _try_points_text_trigger(update, context, trigger_text)
    if handled:
        return True

    return await _try_teacher_search_trigger(update, context, chat_id, trigger_text)
