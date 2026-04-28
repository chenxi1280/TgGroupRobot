from __future__ import annotations


def get_match_type_label(match_type: str) -> str:
    labels = {
        "exact": "精确匹配：消息必须完全等于违禁词",
        "contains": "包含/模糊匹配：消息里出现这个词就拦截",
        "regex": "正则匹配：高级规则",
    }
    return labels.get(match_type, match_type)


def get_action_label(action: str) -> str:
    labels = {
        "delete": "删除消息",
        "mute": "禁言成员",
        "ban": "封禁成员",
        "kick": "踢出成员",
        "warn": "警告成员",
        "notice": "提示消息",
        "none": "未执行处罚",
    }
    return labels.get(action, action)


def get_compact_match_type_label(match_type: str) -> str:
    labels = {
        "exact": "精确匹配",
        "contains": "包含/模糊匹配",
        "regex": "正则匹配",
    }
    return labels.get(match_type, match_type)


def normalize_match_type_input(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "exact": "exact",
        "精确": "exact",
        "精确匹配": "exact",
        "完全匹配": "exact",
        "等于": "exact",
        "contains": "contains",
        "contain": "contains",
        "包含": "contains",
        "包含匹配": "contains",
        "模糊": "contains",
        "模糊匹配": "contains",
        "regex": "regex",
        "regexp": "regex",
        "正则": "regex",
        "正则匹配": "regex",
        "正则表达式": "regex",
    }
    return mapping.get(normalized, normalized)


def normalize_action_input(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "delete": "delete",
        "删除": "delete",
        "删除消息": "delete",
        "mute": "mute",
        "禁言": "mute",
        "禁言成员": "mute",
        "ban": "ban",
        "封禁": "ban",
        "封禁成员": "ban",
    }
    return mapping.get(normalized, normalized)


def normalize_bool_input(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "on", "是", "开", "开启", "启用", "需要", "发送"}
