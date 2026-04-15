from __future__ import annotations

from typing import TypeVar

from telegram.ext import ContextTypes

from backend.shared.callback_parser import CallbackParser

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
        if cb.length() >= 4:
            chat_first = _parse_int_silent(cb.get(2))
            if chat_first is not None:
                return chat_first
            return _parse_int_silent(cb.get(3))
        return None

    if action == "renewal":
        if cb.length() >= 4:
            return cb.get_int_optional(3)
        if cb.length() >= 3:
            return cb.get_int_optional(2)
        return None

    if cb.length() >= 3:
        return cb.get_int_optional(2)
    return None


def _resolve_private_scoped_target_chat_id(cb: CallbackParser) -> int | None:
    prefix = cb.get(0)
    if prefix == "adm":
        return _resolve_private_admin_target_chat_id(cb)

    if prefix == "ali":
        action = cb.get(1)
        if action in {"members", "invite"}:
            return cb.get_int_optional(2)
        if action in {"jointban", "leave"}:
            return cb.get_int_optional(2)
        if action in {"create", "join"}:
            return cb.get_int_optional(3)
        if action == "home":
            return cb.get_int_optional(2)
        return None

    if prefix == "gfw":
        action = cb.get(1)
        if action in {"home", "audit", "toggle", "mode"}:
            return cb.get_int_optional(2)
        if action in {"keywords", "source"}:
            return cb.get_int_optional(3)
        return None

    if prefix == "grg":
        action = cb.get(1)
        if action in {"home", "toggle", "badge", "summary"}:
            return cb.get_int_optional(2)
        if action in {"teacher", "wl"}:
            return cb.get_int_optional(3)
        if action == "limit":
            return cb.get_int_optional(3) if cb.get(2) in {"interval", "max"} else cb.get_int_optional(2)
        return None

    if prefix == "tsearch":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action in {"toggle", "attendance"}:
            return cb.get_int_optional(3)
        if action in {"delete_mode", "delegate"}:
            return cb.get_int_optional(2)
        if action == "open_course":
            return cb.get_int_optional(3)
        return None

    if prefix == "crv":
        action = cb.get(1)
        if action == "home":
            return cb.get_int_optional(2)
        if action in {
            "toggle",
            "mode",
            "lookup",
            "publish_target",
            "approver",
            "template",
            "reward",
            "submit_cmd",
            "rank_cmd",
            "fields",
            "reports",
            "report",
        }:
            return cb.get_int_optional(2)
        return None

    if prefix == "auc":
        action = cb.get(1)
        if action in {"home", "toggle", "perm", "points_mode", "list", "detail"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "btm":
        action = cb.get(1)
        if action in {"home", "toggle", "text", "layout", "generate", "repeat", "button"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "gm":
        action = cb.get(1)
        if action in {"home", "toggle", "rake", "auto", "delete_mode", "rounds", "help", "detail"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "guess":
        action = cb.get(1)
        if action in {"home", "create", "list", "settings", "detail", "open", "cancel"}:
            return cb.get_int_optional(2)
        return None

    if prefix == "act":
        action = cb.get(1)
        if action in {"home", "egg", "chat"}:
            return cb.get_int_optional(2)
        return None

    return None


def _get_import_state(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, mode: str) -> dict:
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
