from __future__ import annotations

import copy
import re

from backend.platform.db.schema.models.core import ChatSettings

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.|t\.me/|telegram\.me/|tg://)\S+")
ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
AT_ID_RE = re.compile(r"@(-?\d{5,})")
AD_KEYWORDS = {
    "兼职",
    "引流",
    "副业",
    "稳赚",
    "空投",
    "上车",
    "拉新",
    "代理",
    "推广",
    "点击链接",
    "私聊",
    "whatsapp",
    "telegram",
    "返利",
}

DEFAULT_RULES: dict[str, object] = {
    "ai_text": False,
    "global_ads": False,
    "flood_attack": False,
    "banned_accounts": False,
    "ai_image_ads": False,
    "block_links": False,
    "block_channel_alias": False,
    "block_forwards": False,
    "block_mentions": False,
    "block_eth_address": False,
    "clear_commands": False,
    "block_long_content": False,
    "message_max_length": 500,
    "name_max_length": 32,
    "exception_user_ids": [],
    "exception_chat_ids": [],
    "banned_user_ids": [],
    "blocked_forward_chat_ids": [],
    "blocked_forward_user_ids": [],
    "blocked_mention_ids": [],
    "link_blacklist": [],
    "garbage_guard": {},
}


def get_antispam_rules(settings: ChatSettings) -> dict[str, object]:
    """获取完整规则配置（为缺省字段补默认值）"""
    rules = copy.deepcopy(DEFAULT_RULES)
    raw = settings.anti_spam_rules or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in rules:
                rules[k] = v

    # 类型兜底
    for list_key in [
        "exception_user_ids",
        "exception_chat_ids",
        "banned_user_ids",
        "blocked_forward_chat_ids",
        "blocked_forward_user_ids",
        "blocked_mention_ids",
        "link_blacklist",
    ]:
        if not isinstance(rules.get(list_key), list):
            rules[list_key] = []

    for int_key, default_value in [
        ("message_max_length", 500),
        ("name_max_length", 32),
    ]:
        try:
            rules[int_key] = int(rules.get(int_key, default_value))
        except (TypeError, ValueError):
            rules[int_key] = default_value

    for bool_key in [
        "ai_text",
        "global_ads",
        "flood_attack",
        "banned_accounts",
        "ai_image_ads",
        "block_links",
        "block_channel_alias",
        "block_forwards",
        "block_mentions",
        "block_eth_address",
        "clear_commands",
        "block_long_content",
    ]:
        rules[bool_key] = bool(rules.get(bool_key))

    return rules


def _to_int_list(values: list[object]) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result
