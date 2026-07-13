from __future__ import annotations

from typing import TypeVar

from telegram.ext import ContextTypes

from backend.shared.callback_parser import CallbackParser
_RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_3 = 3
_RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_4 = 4
_RESOLVE_PRIVATE_SCOPED_TARGET_CHAT_ID_THRESHOLD_4 = 4


T = TypeVar("T")


def _parse_int_silent(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cycle_config_value(current: T, options: list[T]) -> T:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _resolve_private_admin_target_chat_id(cb: CallbackParser) -> int | None:
    """严格解析私聊管理回调中的目标群组 ID。"""
    action = cb.get(1)
    if action in {"switch_group", "back_to_main"}:
        return 0

    if action == "menu":
        if cb.length() >= _RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_4:
            chat_first = _parse_int_silent(cb.get(2))
            if chat_first is not None:
                return chat_first
            return _parse_int_silent(cb.get(3))
        return None

    if action == "renewal":
        if cb.length() >= _RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_4:
            return cb.get_int_optional(3)
        if cb.length() >= _RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_3:
            return cb.get_int_optional(2)
        return None

    if cb.length() >= _RESOLVE_PRIVATE_ADMIN_TARGET_CHAT_ID_THRESHOLD_3:
        return cb.get_int_optional(2)
    return None


def _resolve_alliance_target(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    if action in {"members", "invite"}:
        index = 3 if cb.length() >= _RESOLVE_PRIVATE_SCOPED_TARGET_CHAT_ID_THRESHOLD_4 else 2
        return cb.get_int_optional(index)
    if action in {"jointban", "leave"}:
        return cb.get_int_optional(3 if cb.get(2) == "toggle" else 2)
    indices = {"create": 3, "join": 3, "home": 2}
    index = indices.get(action)
    return cb.get_int_optional(index) if index is not None else None


def _resolve_garage_forward_target(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    if action in {"home", "audit", "toggle", "mode", "btn_toggle"}:
        return cb.get_int_optional(2)
    if action in {"keywords", "source", "buttons"}:
        return cb.get_int_optional(3)
    return None


def _resolve_garage_auth_target(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    if action in {"home", "toggle", "badge"}:
        return cb.get_int_optional(2)
    if action == "summary":
        index = 3 if cb.length() >= _RESOLVE_PRIVATE_SCOPED_TARGET_CHAT_ID_THRESHOLD_4 else 2
        return cb.get_int_optional(index)
    if action in {"teacher", "wl"}:
        return cb.get_int_optional(3)
    if action != "limit":
        return None
    index = 3 if cb.get(2) in {"toggle", "mode", "interval", "max"} else 2
    return cb.get_int_optional(index)


def _resolve_teacher_search_target(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    direct_indices = {
        "home": 2, "toggle": 3, "attendance": 3, "attendance_word": 3,
        "attendance_source": 3, "attendance_source_mode": 3,
        "delete_mode": 2, "footer": 3, "open_course": 3,
    }
    if action in direct_indices:
        return cb.get_int_optional(direct_indices[action])
    if action == "attendance_mode":
        return cb.get_int_optional(3 if cb.get(2) in {"menu", "set"} else 2)
    if action == "delegate":
        return cb.get_int_optional(3 if cb.get(2) == "start" else 2)
    return None


def _resolve_car_review_target(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    variable = {"submit_cmd", "rank_cmd", "approver", "template"}
    direct = {
        "home", "toggle", "mode", "board", "lookup", "publish_target", "reward",
        "fields", "field_add", "field_edit", "field_tog", "reports", "report",
    }
    if action in variable:
        index = 3 if cb.length() >= _RESOLVE_PRIVATE_SCOPED_TARGET_CHAT_ID_THRESHOLD_4 else 2
        return cb.get_int_optional(index)
    return cb.get_int_optional(2) if action in direct else None


_STANDARD_SCOPED_ACTIONS = {
    "auc": {"home", "toggle", "perm", "points_mode", "list", "detail"},
    "btm": {"home", "toggle", "text", "layout", "generate", "repeat", "button"},
    "gm": {"home", "toggle", "rake", "auto", "delete_mode", "rounds", "help", "detail", "points"},
    "guess": {"home", "create", "list", "settings", "detail", "open", "cancel"},
    "act": {"home", "egg", "chat"},
    "qpub": {"home", "input", "clear", "send"},
}


def _resolve_standard_scoped_target(cb: CallbackParser) -> int | None:
    actions = _STANDARD_SCOPED_ACTIONS.get(cb.get(0), set())
    return cb.get_int_optional(2) if cb.get(1) in actions else None


def _resolve_private_scoped_target_chat_id(cb: CallbackParser) -> int | None:
    prefix = cb.get(0)
    if prefix == "adm":
        return _resolve_private_admin_target_chat_id(cb)
    resolvers = {
        "ali": _resolve_alliance_target,
        "gfw": _resolve_garage_forward_target,
        "grg": _resolve_garage_auth_target,
        "tsearch": _resolve_teacher_search_target,
        "crv": _resolve_car_review_target,
    }
    resolver = resolvers.get(prefix, _resolve_standard_scoped_target)
    return resolver(cb)


def _get_import_state(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, *, mode: str) -> dict:
    key = f"import_settings:{mode}"
    state = context.user_data.get(key)
    if not isinstance(state, dict) or state.get("owner_id") != user_id or state.get("mode") != mode:
        state = {"owner_id": user_id, "target_chat_id": None, "source_chat_id": None, "modules": [], "mode": mode}
        context.user_data[key] = state
    if mode == "import":
        state["target_chat_id"] = chat_id
    if mode == "clone":
        state["source_chat_id"] = chat_id
    return state


def _get_quick_publish_draft(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict:
    drafts = context.user_data.setdefault("quick_publish_draft", {})
    key = str(chat_id)
    if key not in drafts:
        drafts[key] = {"text": "", "media_type": None, "media_file_id": None, "buttons": []}
    return drafts[key]


def _get_action_label(action: str) -> str:
    labels = {
        "delete": "删除消息",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)


def _normalize_mall_order_status(raw_status: str) -> str:
    normalized = (raw_status or "").strip().lower()
    mapping = {
        "a": "all",
        "c": "created",
        "f": "fulfilled",
        "x": "canceled",
        "r": "refunded",
        "all": "all",
        "created": "created",
        "fulfilled": "fulfilled",
        "canceled": "canceled",
        "refunded": "refunded",
    }
    return mapping.get(normalized, "all")


def _normalize_car_review_report_status(raw_status: str) -> str:
    normalized = (raw_status or "").strip().lower()
    mapping = {
        "0": "all",
        "p": "pending",
        "a": "approved",
        "u": "published",
        "r": "rejected",
        "all": "all",
        "pending": "pending",
        "approved": "approved",
        "published": "published",
        "rejected": "rejected",
    }
    return mapping.get(normalized, "all")


def _car_review_report_status_code(status: str) -> str:
    mapping = {
        "all": "0",
        "pending": "p",
        "approved": "a",
        "published": "u",
        "rejected": "r",
    }
    return mapping.get((status or "").strip().lower(), "0")


def _normalize_gfw_audit_result(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    mapping = {
        "a": "all",
        "s": "success",
        "k": "skipped",
        "f": "failed",
        "all": "all",
        "success": "success",
        "skipped": "skipped",
        "failed": "failed",
    }
    return mapping.get(normalized, "all")


def _gfw_audit_result_code(result: str) -> str:
    mapping = {
        "all": "a",
        "success": "s",
        "skipped": "k",
        "failed": "f",
    }
    return mapping.get((result or "").strip().lower(), "a")


def _garage_forward_mode_label(mode: str) -> str:
    labels = {
        "all": "全部",
        "text": "仅文本",
        "media": "仅媒体",
        "keyword": "关键词",
    }
    return labels.get((mode or "all").strip().lower(), "全部")


__all__ = [name for name in globals() if not name.startswith("__")]
