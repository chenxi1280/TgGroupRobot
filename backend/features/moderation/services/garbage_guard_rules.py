from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from backend.platform.db.schema.models.core import ChatSettings


RuleId = str


@dataclass(frozen=True)
class GarbageRuleDefinition:
    key: RuleId
    label: str
    title: str
    description: str


RULE_ORDER: tuple[RuleId, ...] = (
    "banned_words",
    "long_message",
    "long_name",
    "block_links",
    "block_buttons",
    "spam_user",
    "block_forwards",
    "flood",
    "manual_warning",
    "leave_ban",
    "quick_reply_actions",
)

DEFAULT_DELETE_ON_ENABLE_RULES: set[RuleId] = {
    "banned_words",
    "long_message",
    "long_name",
    "block_links",
    "block_buttons",
    "spam_user",
    "block_forwards",
    "flood",
}

DEFAULT_NOTICE_ON_ENABLE_RULES: set[RuleId] = {
    "banned_words",
    "long_message",
    "long_name",
    "block_links",
    "block_buttons",
    "spam_user",
    "block_forwards",
    "flood",
    "manual_warning",
}

RULE_DEFINITIONS: dict[RuleId, GarbageRuleDefinition] = {
    "banned_words": GarbageRuleDefinition(
        "banned_words",
        "拦截违禁词",
        "☂️ 拦截违禁词",
        "检测用户的昵称、发送的消息中是否含有设置的违禁词，支持 emoji 和文字。",
    ),
    "long_message": GarbageRuleDefinition(
        "long_message",
        "禁止长内容",
        "☂️ 禁止长内容",
        "检测用户发送的消息长度，超过配置限额时处罚。",
    ),
    "long_name": GarbageRuleDefinition(
        "long_name",
        "禁止长昵称",
        "☂️ 禁止长昵称",
        "检测用户发言时的昵称长度，超过配置限额时处罚。",
    ),
    "block_links": GarbageRuleDefinition(
        "block_links",
        "禁止发链接",
        "☂️ 禁止发链接",
        "检测用户发送的消息中是否包含链接。",
    ),
    "block_buttons": GarbageRuleDefinition(
        "block_buttons",
        "禁止发送按钮",
        "☂️ 禁止发按钮",
        "检测用户发送的消息是否带有按钮，用于防护垃圾广告带一堆按钮刷屏的情景。",
    ),
    "spam_user": GarbageRuleDefinition(
        "spam_user",
        "禁止垃圾用户",
        "☂️ 禁止垃圾用户",
        "检测无用户名或外文昵称用户，可分别开启。",
    ),
    "block_forwards": GarbageRuleDefinition(
        "block_forwards",
        "禁止转发引用",
        "☂️ 禁止转发链接",
        "检测用户发送的消息是否是转发的外部信息，包括转发个人、频道、群组消息。",
    ),
    "flood": GarbageRuleDefinition(
        "flood",
        "禁止发言刷屏",
        "☂️ 禁止发言刷屏",
        "检测短时间大量发言，超过配置限额时处罚。",
    ),
    "manual_warning": GarbageRuleDefinition(
        "manual_warning",
        "人工警告",
        "👮 人工警告用户",
        "有封禁权限的管理员，可以回复用户消息发送 warn 或 警告，超过次数后进行惩罚，用户警告次数 7 天后清零。",
    ),
    "leave_ban": GarbageRuleDefinition(
        "leave_ban",
        "离群封禁",
        "☂️ 离群封禁",
        "用户离开群组时自动封禁，避免反复退群再进。",
    ),
    "quick_reply_actions": GarbageRuleDefinition(
        "quick_reply_actions",
        "快捷回复操作",
        "👮 快捷回复操作",
        "管理员引用成员消息后回复配置词，快速禁言或踢出目标成员。",
    ),
}

DEFAULT_RULE_ACTION: dict[str, Any] = {
    "enabled": False,
    "delete_message": True,
    "delete_configured": False,
    "warn_enabled": False,
    "warn_threshold": 3,
    "mute_enabled": False,
    "mute_seconds": 3600,
    "kick_enabled": False,
    "notice_enabled": False,
    "notice_configured": False,
    "notice_text": "",
    "notice_delete_seconds": 10,
}

DEFAULT_RULES: dict[RuleId, dict[str, Any]] = {
    rule_id: copy.deepcopy(DEFAULT_RULE_ACTION) for rule_id in RULE_ORDER
}
DEFAULT_RULES["manual_warning"].update({"delete_message": False, "warn_enabled": True})
DEFAULT_RULES["leave_ban"].update({"delete_message": True})
DEFAULT_RULES["quick_reply_actions"].update(
    {
        "delete_message": True,
        "mute_keyword": "j",
        "kick_keyword": "t",
        "notice_enabled": False,
    }
)
DEFAULT_RULES["long_message"]["message_max_length"] = 500
DEFAULT_RULES["long_name"]["name_max_length"] = 32
DEFAULT_RULES["spam_user"].update({"check_no_username": True, "check_foreign_name": True})
DEFAULT_RULES["flood"].update({"messages": 5, "seconds": 5})

DEFAULT_GARBAGE_CONFIG: dict[str, Any] = {
    "global_whitelist_user_ids": [],
    "rules": DEFAULT_RULES,
}

RULE_CYCLE_VALUES: dict[str, list[int]] = {
    "message_max_length": [50, 100, 200, 500, 1000, 2000],
    "name_max_length": [12, 16, 24, 32, 48, 64],
    "warn_threshold": [1, 2, 3, 5, 10],
    "mute_seconds": [300, 600, 1800, 3600, 7200, 86400],
    "notice_delete_seconds": [5, 10, 30, 60, 300],
    "messages": [3, 5, 7, 10],
    "seconds": [3, 5, 10, 15, 30],
}


def _normalize_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启", "是"}
    return bool(value)


def _normalize_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _normalize_keyword(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    keyword = value.strip()
    return keyword or default


def _merge_rule(rule_id: RuleId, raw: Any) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_RULES[rule_id])
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in merged:
                merged[key] = value

    for bool_key in [
        "enabled",
        "delete_message",
        "delete_configured",
        "warn_enabled",
        "mute_enabled",
        "kick_enabled",
        "notice_enabled",
        "notice_configured",
        "check_no_username",
        "check_foreign_name",
    ]:
        if bool_key in merged:
            merged[bool_key] = _normalize_bool(merged.get(bool_key), bool(DEFAULT_RULES[rule_id].get(bool_key, False)))

    for int_key, minimum in [
        ("warn_threshold", 1),
        ("mute_seconds", 1),
        ("notice_delete_seconds", 1),
        ("message_max_length", 20),
        ("name_max_length", 2),
        ("messages", 2),
        ("seconds", 1),
    ]:
        if int_key in merged:
            merged[int_key] = _normalize_int(merged.get(int_key), int(DEFAULT_RULES[rule_id].get(int_key, 1)), minimum)

    if not isinstance(merged.get("notice_text"), str):
        merged["notice_text"] = ""

    for keyword_key in ["mute_keyword", "kick_keyword"]:
        if keyword_key in merged:
            merged[keyword_key] = _normalize_keyword(
                merged.get(keyword_key),
                str(DEFAULT_RULES[rule_id].get(keyword_key, "")),
            )

    return merged


def get_garbage_config(settings: ChatSettings) -> dict[str, Any]:
    raw_rules = getattr(settings, "anti_spam_rules", None) or {}
    if not isinstance(raw_rules, dict):
        raw_rules = {}

    raw_config = raw_rules.get("garbage_guard")
    config = copy.deepcopy(DEFAULT_GARBAGE_CONFIG)

    if isinstance(raw_config, dict):
        config["global_whitelist_user_ids"] = _normalize_int_list(
            raw_config.get("global_whitelist_user_ids", raw_rules.get("exception_user_ids", []))
        )
        raw_rule_config = raw_config.get("rules") if isinstance(raw_config.get("rules"), dict) else {}
        for rule_id in RULE_ORDER:
            config["rules"][rule_id] = _merge_rule(rule_id, raw_rule_config.get(rule_id))
    else:
        config["global_whitelist_user_ids"] = _normalize_int_list(raw_rules.get("exception_user_ids", []))
        for rule_id in RULE_ORDER:
            config["rules"][rule_id] = _merge_rule(rule_id, None)

        # Legacy anti-spam options are mapped into the new rule surface for a smooth upgrade.
        if _normalize_bool(raw_rules.get("block_long_content")):
            config["rules"]["long_message"]["enabled"] = True
            config["rules"]["long_name"]["enabled"] = True
        if _normalize_bool(raw_rules.get("block_links")):
            config["rules"]["block_links"]["enabled"] = True
        if _normalize_bool(raw_rules.get("block_forwards")):
            config["rules"]["block_forwards"]["enabled"] = True

    config["rules"]["long_message"]["message_max_length"] = _normalize_int(
        config["rules"]["long_message"].get("message_max_length", raw_rules.get("message_max_length")),
        500,
        20,
    )
    config["rules"]["long_name"]["name_max_length"] = _normalize_int(
        config["rules"]["long_name"].get("name_max_length", raw_rules.get("name_max_length")),
        32,
        2,
    )
    config["rules"]["flood"]["enabled"] = bool(config["rules"]["flood"].get("enabled")) or bool(
        getattr(settings, "anti_flood_enabled", False)
    )
    config["rules"]["flood"]["messages"] = _normalize_int(
        config["rules"]["flood"].get("messages", getattr(settings, "anti_flood_messages", 5)),
        int(getattr(settings, "anti_flood_messages", 5) or 5),
        2,
    )
    config["rules"]["flood"]["seconds"] = _normalize_int(
        config["rules"]["flood"].get("seconds", getattr(settings, "anti_flood_seconds", 5)),
        int(getattr(settings, "anti_flood_seconds", 5) or 5),
        1,
    )
    config["rules"]["flood"]["mute_seconds"] = _normalize_int(
        config["rules"]["flood"].get("mute_seconds", getattr(settings, "anti_flood_mute_duration", 3600)),
        int(getattr(settings, "anti_flood_mute_duration", 3600) or 3600),
        1,
    )
    for rule_id in DEFAULT_DELETE_ON_ENABLE_RULES:
        rule = config["rules"][rule_id]
        if bool(rule.get("enabled")) and not bool(rule.get("delete_configured")):
            rule["delete_message"] = True
    for rule_id in DEFAULT_NOTICE_ON_ENABLE_RULES:
        rule = config["rules"][rule_id]
        if bool(rule.get("enabled")) and not bool(rule.get("notice_configured")):
            rule["notice_enabled"] = True
    return config


def has_explicit_garbage_config(settings: ChatSettings) -> bool:
    raw_rules = getattr(settings, "anti_spam_rules", None) or {}
    return isinstance(raw_rules, dict) and isinstance(raw_rules.get("garbage_guard"), dict)


def save_garbage_config(settings: ChatSettings, config: dict[str, Any]) -> None:
    raw_rules = getattr(settings, "anti_spam_rules", None) or {}
    if not isinstance(raw_rules, dict):
        raw_rules = {}
    else:
        raw_rules = copy.deepcopy(raw_rules)
    normalized = copy.deepcopy(DEFAULT_GARBAGE_CONFIG)
    normalized["global_whitelist_user_ids"] = _normalize_int_list(config.get("global_whitelist_user_ids", []))
    raw_rule_config = config.get("rules") if isinstance(config.get("rules"), dict) else {}
    for rule_id in RULE_ORDER:
        normalized["rules"][rule_id] = _merge_rule(rule_id, raw_rule_config.get(rule_id))

    raw_rules["garbage_guard"] = normalized
    raw_rules["exception_user_ids"] = normalized["global_whitelist_user_ids"]
    raw_rules["message_max_length"] = normalized["rules"]["long_message"]["message_max_length"]
    raw_rules["name_max_length"] = normalized["rules"]["long_name"]["name_max_length"]
    raw_rules["block_links"] = normalized["rules"]["block_links"]["enabled"]
    raw_rules["block_forwards"] = normalized["rules"]["block_forwards"]["enabled"]
    raw_rules["block_long_content"] = bool(
        normalized["rules"]["long_message"]["enabled"] or normalized["rules"]["long_name"]["enabled"]
    )
    settings.anti_spam_rules = raw_rules

    flood = normalized["rules"]["flood"]
    settings.anti_flood_enabled = bool(flood["enabled"])
    settings.anti_flood_messages = int(flood["messages"])
    settings.anti_flood_seconds = int(flood["seconds"])
    settings.anti_flood_mute_duration = int(flood["mute_seconds"])
    settings.anti_flood_cleanup_messages = bool(flood["delete_message"])


def get_rule_config(settings: ChatSettings, rule_id: RuleId) -> dict[str, Any]:
    return get_garbage_config(settings)["rules"].get(rule_id, _merge_rule(rule_id, None))


def set_rule_config(settings: ChatSettings, rule_id: RuleId, updates: dict[str, Any]) -> dict[str, Any]:
    config = get_garbage_config(settings)
    rule = config["rules"].get(rule_id, _merge_rule(rule_id, None))
    if "delete_message" in updates:
        updates = {**updates, "delete_configured": True}
    if "notice_enabled" in updates:
        updates = {**updates, "notice_configured": True}
    rule.update(updates)
    config["rules"][rule_id] = _merge_rule(rule_id, rule)
    save_garbage_config(settings, config)
    return config["rules"][rule_id]


def get_global_whitelist_user_ids(settings: ChatSettings) -> list[int]:
    return get_garbage_config(settings)["global_whitelist_user_ids"]


def set_global_whitelist_user_ids(settings: ChatSettings, user_ids: list[int]) -> None:
    config = get_garbage_config(settings)
    config["global_whitelist_user_ids"] = sorted(set(_normalize_int_list(user_ids)))
    save_garbage_config(settings, config)


def is_global_whitelisted(settings: ChatSettings, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in set(get_global_whitelist_user_ids(settings))


def any_garbage_rule_enabled(settings: ChatSettings) -> bool:
    config = get_garbage_config(settings)
    return any(bool(config["rules"][rule_id].get("enabled")) for rule_id in RULE_ORDER)


def cycle_rule_value(settings: ChatSettings, rule_id: RuleId, field: str) -> dict[str, Any]:
    rule = get_rule_config(settings, rule_id)
    values = RULE_CYCLE_VALUES[field]
    current = int(rule.get(field, values[0]))
    next_value = values[0] if current not in values else values[(values.index(current) + 1) % len(values)]
    return set_rule_config(settings, rule_id, {field: next_value})
