from __future__ import annotations

JOIN_SPAM_RULE_VALUES = [1, 2, 3, 4, 5]
JOIN_SPAM_TIP_DELETE_VALUES = [30, 60, 120, 300]
JOIN_SELF_REVIEW_TIMEOUT_VALUES = [60, 120, 300, 600]
JOIN_BURST_WINDOW_VALUES = [10, 30, 60, 120]
JOIN_BURST_THRESHOLD_VALUES = [3, 5, 10, 15]
NEW_MEMBER_WARN_DELETE_VALUES = [30, 60, 120, 300]
FORCE_SUBSCRIBE_DELETE_AFTER_VALUES = [15, 30, 60, 90, 120, 300]
VERIFICATION_TIMEOUT_VALUES = [60, 120, 300, 600, 1800, 3600]
VERIFICATION_DIRECT_MUTE_DURATION_VALUES = [0, 3600, 86400, 604800]

VERIFICATION_ACTION_LABELS = {
    "none": "不额外处理",
    "mute": "禁言",
    "kick": "踢出",
}

VERIFICATION_MODE_LABELS = {
    "button": "简单接受条约",
    "math": "简单加减法",
    "mute": "直接禁言新人",
}

JOIN_SELF_REVIEW_ACTION_LABELS = {
    "reject_allow_retry": "🔁 驳回可重试",
    "reject_block": "⛔ 驳回并拉黑",
}

JOIN_BURST_TIP_MODE_LABELS = {
    "no_tip": "🔕 不提示",
    "tip_and_delete": "🧹 提示后删除",
}

__all__ = [name for name in globals() if not name.startswith("__")]
