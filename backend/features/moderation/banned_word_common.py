from __future__ import annotations


def get_match_type_label(match_type: str) -> str:
    labels = {
        "exact": "精确匹配",
        "contains": "包含匹配",
        "regex": "正则表达式",
    }
    return labels.get(match_type, match_type)


def get_action_label(action: str) -> str:
    labels = {
        "delete": "删除",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)
