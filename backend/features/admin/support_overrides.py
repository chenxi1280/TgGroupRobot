from __future__ import annotations

from backend.features.activity.services.auction_service import (
    get_or_create_setting as get_auction_setting,
    list_auctions,
    list_recent_auctions,
)
from backend.features.activity.services.engagement_service import (
    get_egg_event,
    get_egg_event_counts,
    get_latest_running_egg_event,
    get_or_create_chat_reward as get_engagement_chat_reward,
    get_recent_chat_reward_stats,
)
from backend.features.activity.services.game_service import (
    get_or_create_setting as get_game_setting,
    get_rake_owner_label as get_game_rake_owner_label,
)
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user

_ORIG_get_chat_settings = get_chat_settings
_ORIG_answer_callback_query_safely = answer_callback_query_safely
_ORIG_clear_user_state = clear_user_state
_ORIG_ensure_user = ensure_user
_ORIG_set_user_state = set_user_state
_ORIG_get_egg_event_counts = get_egg_event_counts
_ORIG_get_latest_running_egg_event = get_latest_running_egg_event
_ORIG_get_engagement_chat_reward = get_engagement_chat_reward
_ORIG_get_recent_chat_reward_stats = get_recent_chat_reward_stats
_ORIG_get_egg_event = get_egg_event
_ORIG_get_game_setting = get_game_setting
_ORIG_get_game_rake_owner_label = get_game_rake_owner_label
_ORIG_get_auction_setting = get_auction_setting
_ORIG_list_recent_auctions = list_recent_auctions
_ORIG_list_auctions = list_auctions
_ORIG_is_user_admin = is_user_admin


def _resolve_admin_override(name: str, default):
    import sys

    admin_module = sys.modules.get("backend.features.admin.admin_handler")
    if admin_module is None:
        return default
    return getattr(admin_module, name, default)


async def get_chat_settings(*args, **kwargs):
    return await _resolve_admin_override("get_chat_settings", _ORIG_get_chat_settings)(*args, **kwargs)


async def answer_callback_query_safely(*args, **kwargs):
    return await _resolve_admin_override(
        "answer_callback_query_safely",
        _ORIG_answer_callback_query_safely,
    )(*args, **kwargs)


async def clear_user_state(*args, **kwargs):
    return await _resolve_admin_override("clear_user_state", _ORIG_clear_user_state)(*args, **kwargs)


async def ensure_user(*args, **kwargs):
    return await _resolve_admin_override("ensure_user", _ORIG_ensure_user)(*args, **kwargs)


async def set_user_state(*args, **kwargs):
    return await _resolve_admin_override("set_user_state", _ORIG_set_user_state)(*args, **kwargs)


async def get_egg_event_counts(*args, **kwargs):
    return await _resolve_admin_override("get_egg_event_counts", _ORIG_get_egg_event_counts)(*args, **kwargs)


async def get_latest_running_egg_event(*args, **kwargs):
    return await _resolve_admin_override(
        "get_latest_running_egg_event",
        _ORIG_get_latest_running_egg_event,
    )(*args, **kwargs)


async def get_engagement_chat_reward(*args, **kwargs):
    return await _resolve_admin_override(
        "get_engagement_chat_reward",
        _ORIG_get_engagement_chat_reward,
    )(*args, **kwargs)


async def get_recent_chat_reward_stats(*args, **kwargs):
    return await _resolve_admin_override(
        "get_recent_chat_reward_stats",
        _ORIG_get_recent_chat_reward_stats,
    )(*args, **kwargs)


async def get_egg_event(*args, **kwargs):
    return await _resolve_admin_override("get_egg_event", _ORIG_get_egg_event)(*args, **kwargs)


async def get_game_setting(*args, **kwargs):
    return await _resolve_admin_override("get_game_setting", _ORIG_get_game_setting)(*args, **kwargs)


def get_game_rake_owner_label(*args, **kwargs):
    return _resolve_admin_override(
        "get_game_rake_owner_label",
        _ORIG_get_game_rake_owner_label,
    )(*args, **kwargs)


async def get_auction_setting(*args, **kwargs):
    return await _resolve_admin_override("get_auction_setting", _ORIG_get_auction_setting)(*args, **kwargs)


async def list_recent_auctions(*args, **kwargs):
    return await _resolve_admin_override(
        "list_recent_auctions",
        _ORIG_list_recent_auctions,
    )(*args, **kwargs)


async def list_auctions(*args, **kwargs):
    return await _resolve_admin_override("list_auctions", _ORIG_list_auctions)(*args, **kwargs)


async def is_user_admin(*args, **kwargs):
    return await _resolve_admin_override("is_user_admin", _ORIG_is_user_admin)(*args, **kwargs)


__all__ = [name for name in globals() if not name.startswith("__")]
