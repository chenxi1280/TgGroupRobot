from __future__ import annotations

from backend.platform.db.schema.models.core import ConversationState

RULE_CODE_MAP = {
    "ait": "ai_text",
    "gad": "global_ads",
    "fld": "flood_attack",
    "ban": "banned_accounts",
    "aig": "ai_image_ads",
    "lnk": "block_links",
    "als": "block_channel_alias",
    "fwd": "block_forwards",
    "men": "block_mentions",
    "eth": "block_eth_address",
    "cmd": "clear_commands",
    "lng": "block_long_content",
}

SPAM_ACTIONS = ["delete", "mute", "ban"]
SPAM_MUTE_VALUES = [300, 600, 1800, 3600, 7200]
SPAM_NOTIFY_SEC_VALUES = [60, 300, 600, 1800]
SPAM_REPEAT_MESSAGES_VALUES = [2, 3, 5, 8]
SPAM_REPEAT_SECONDS_VALUES = [5, 10, 15, 30]

_BOOL_TRUE = {"开启", "开", "on", "true", "1", "yes", "是"}
_BOOL_TRUE_NORMALIZED = {x.lower() for x in _BOOL_TRUE}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in _BOOL_TRUE_NORMALIZED


def _parse_int(value: str, min_value: int) -> int | None:
    try:
        return max(min_value, int(value.strip()))
    except (TypeError, ValueError):
        return None


def _cycle(current: int | str, options: list[int | str]) -> int | str:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_int_list(value: str) -> list[int]:
    values: list[int] = []
    for item in _split_list(value):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def _resolve_target_chat_id(state: ConversationState) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    return None
