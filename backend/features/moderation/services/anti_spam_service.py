from __future__ import annotations

from telegram import Message

from backend.features.moderation.services.anti_spam_detection import (
    _contains_ad_keyword,
    _display_name_len,
    _extract_mentioned_ids,
    _forward_source_ids,
    _looks_like_text_spam,
    _message_has_media,
    _normalize_text,
    detect_spam_violation as _detect_spam_violation,
)
from backend.features.moderation.services.anti_spam_punishment import execute_spam_punishment
from backend.features.moderation.services.anti_spam_rules import (
    AD_KEYWORDS,
    AT_ID_RE,
    DEFAULT_RULES,
    ETH_RE,
    URL_RE,
    _to_int_list,
    get_antispam_rules,
)
from backend.features.moderation.services.anti_spam_tracker import AntiSpamTracker
from backend.features.moderation.services.anti_spam_types import SpamMessageRecord, SpamViolation
from backend.platform.db.schema.models.core import ChatSettings

_tracker = AntiSpamTracker()


def get_antispam_tracker() -> AntiSpamTracker:
    return _tracker


async def detect_spam_violation(
    settings: ChatSettings,
    message: Message,
    chat_id: int,
    user_id: int,
) -> SpamViolation:
    return await _detect_spam_violation(
        settings,
        message,
        chat_id,
        user_id,
        tracker=get_antispam_tracker(),
    )


async def anti_spam_cleanup_job() -> None:
    await get_antispam_tracker().cleanup_old_records(max_age_seconds=600)


__all__ = [
    "AD_KEYWORDS",
    "AT_ID_RE",
    "AntiSpamTracker",
    "DEFAULT_RULES",
    "ETH_RE",
    "SpamMessageRecord",
    "SpamViolation",
    "URL_RE",
    "_contains_ad_keyword",
    "_display_name_len",
    "_extract_mentioned_ids",
    "_forward_source_ids",
    "_looks_like_text_spam",
    "_message_has_media",
    "_normalize_text",
    "_to_int_list",
    "anti_spam_cleanup_job",
    "detect_spam_violation",
    "execute_spam_punishment",
    "get_antispam_rules",
    "get_antispam_tracker",
]
