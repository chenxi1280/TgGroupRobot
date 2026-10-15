from __future__ import annotations

import structlog

from sqlalchemy import func, select
from telegram.error import BadRequest

from backend.platform.db.schema.models.core import TgUser

log = structlog.get_logger(__name__)

WAIT_VALUE = 0

TOGGLE_FIELDS = frozenset({"all_enabled", "sign_enabled", "message_points_enabled", "invite_points_enabled",
    "points_display_rule_enabled", "points_speech_rank_enabled", "points_personal_speech_enabled"})
EDIT_FIELDS = frozenset({"sign_points", "sign_consecutive", "message_points", "message_daily_limit",
    "message_min_length", "invite_points", "invite_daily_limit", "points_alias", "points_rank_alias",
    "transfer", "admin_add", "admin_deduct", "clear_points"})
MAX_ALIAS_LENGTH = 32
MAX_CONFIG_VALUE = 2147483647
EXPLICIT_TOGGLE_INDEX = 4


def valid_points_toggle(cb, field):
    return field in TOGGLE_FIELDS and (cb.length() <= EXPLICIT_TOGGLE_INDEX or cb.get(EXPLICIT_TOGGLE_INDEX) in {"0", "1"})


async def valid_points_edit(update, context, *, field, chat_id):
    return field in EDIT_FIELDS and await can_configure_points(update, context, chat_id)


def clear_points_input(context):
    context.user_data.pop("points_edit_field", None)
    context.user_data.pop("points_edit_chat_id", None)


async def can_configure_points(update, context, chat_id):
    from backend.shared.services.permission_service import PermissionPolicyService
    return (update.effective_chat is not None and update.effective_chat.type == "private"
            and update.effective_user is not None and isinstance(chat_id, int) and chat_id < 0
            and await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id, capability="points"))


def nonnegative_config_value(text):
    value = int(text.strip())
    if not 0 <= value <= MAX_CONFIG_VALUE:
        raise ValueError("请输入0—2147483647之间的整数")
    return value


async def safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息。"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise


async def resolve_points_target_user(session, raw: str) -> TgUser | None:
    token = raw.strip()
    if not token:
        return None

    if token.lstrip("-").isdigit():
        return await session.get(TgUser, int(token))

    username = token[1:] if token.startswith("@") else token
    username = username.strip().lower()
    if not username:
        return None

    result = await session.execute(
        select(TgUser).where(func.lower(TgUser.username) == username)
    )
    return result.scalar_one_or_none()
