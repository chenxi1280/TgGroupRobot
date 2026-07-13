from __future__ import annotations

from backend.features.group_ops.group_hooks.control_force_subscribe import (  # noqa: F401
    _build_force_subscribe_channel_button,
    _build_force_subscribe_markup,
    _check_force_subscribe,
)
from backend.features.group_ops.group_hooks.control_lock import (  # noqa: F401
    _apply_group_lock_permissions,
    _is_closed_by_schedule,
    _process_group_lock_controls,
)
from backend.features.group_ops.group_hooks.control_new_member import (
    _format_duration_label,
    _get_member_joined_at,
    _message_contains_link,
)
from backend.features.group_ops.group_hooks.control_new_member import _process_new_member_limit as _process_new_member_limit_impl
from backend.features.group_ops.group_hooks.control_night import (
    _is_night_time,
)
from backend.features.group_ops.group_hooks.control_night import _process_night_mode as _process_night_mode_impl
from backend.features.group_ops.group_hooks.control_rename import _process_rename_monitor  # noqa: F401


async def _process_new_member_limit(context, db, chat, *, user, message, settings) -> bool:
    return await _process_new_member_limit_impl(
        context,
        db,
        chat,
        user=user,
        message=message,
        settings=settings,
        joined_at_lookup=_get_member_joined_at,
    )


async def _process_night_mode(context, chat, user, *, message, settings, is_admin: bool) -> bool:
    return await _process_night_mode_impl(
        context,
        chat,
        user,
        message=message,
        settings=settings,
        is_admin=is_admin,
        night_time_check=_is_night_time,
    )

__all__ = [
    "_apply_group_lock_permissions",
    "_build_force_subscribe_channel_button",
    "_build_force_subscribe_markup",
    "_check_force_subscribe",
    "_format_duration_label",
    "_get_member_joined_at",
    "_is_closed_by_schedule",
    "_is_night_time",
    "_message_contains_link",
    "_process_group_lock_controls",
    "_process_new_member_limit",
    "_process_night_mode",
    "_process_rename_monitor",
]
