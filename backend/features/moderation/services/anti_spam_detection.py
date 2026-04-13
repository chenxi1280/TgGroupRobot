from __future__ import annotations

import re

from telegram import Message

from backend.features.moderation.services.anti_spam_rules import (
    AD_KEYWORDS,
    AT_ID_RE,
    ETH_RE,
    URL_RE,
    _to_int_list,
    get_antispam_rules,
)
from backend.features.moderation.services.anti_spam_tracker import AntiSpamTracker
from backend.features.moderation.services.anti_spam_types import SpamViolation
from backend.platform.db.schema.models.core import ChatSettings


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    value = text.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _contains_ad_keyword(text_norm: str) -> bool:
    return any(kw in text_norm for kw in AD_KEYWORDS)


def _looks_like_text_spam(text_norm: str) -> bool:
    # 简单启发式：广告词 + 联系方式/链接/金额诱导
    score = 0
    if URL_RE.search(text_norm):
        score += 2
    if _contains_ad_keyword(text_norm):
        score += 2
    if "@" in text_norm and any(x in text_norm for x in ["联系", "咨询", "私聊"]):
        score += 1
    if any(x in text_norm for x in ["稳赚", "秒到", "返佣", "高收益", "免费领取"]):
        score += 1
    return score >= 3


def _message_has_media(message: Message) -> bool:
    return bool(message.photo or message.video or message.animation or message.document)


def _forward_source_ids(message: Message) -> tuple[int | None, int | None]:
    # 兼容 PTB 新旧结构
    chat_id = None
    user_id = None

    if getattr(message, "forward_from_chat", None) is not None:
        chat_id = message.forward_from_chat.id
    if getattr(message, "forward_from", None) is not None:
        user_id = message.forward_from.id

    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        sender_chat = getattr(origin, "sender_chat", None)
        sender_user = getattr(origin, "sender_user", None)
        if sender_chat is not None:
            chat_id = sender_chat.id
        if sender_user is not None:
            user_id = sender_user.id

    return chat_id, user_id


def _extract_mentioned_ids(message: Message) -> set[int]:
    ids: set[int] = set()
    for entity in [*(message.entities or []), *(message.caption_entities or [])]:
        entity_type = getattr(entity.type, "value", entity.type)
        if entity_type == "text_mention" and entity.user is not None:
            ids.add(entity.user.id)

    text = message.text or message.caption or ""
    for matched in AT_ID_RE.findall(text):
        try:
            ids.add(int(matched))
        except ValueError:
            continue

    return ids


def _display_name_len(message: Message) -> int:
    user = message.from_user
    if user is None:
        return 0
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return len(full_name)


async def detect_spam_violation(
    settings: ChatSettings,
    message: Message,
    chat_id: int,
    user_id: int,
    tracker: AntiSpamTracker,
) -> SpamViolation:
    rules = get_antispam_rules(settings)

    if user_id in set(_to_int_list(rules.get("exception_user_ids", []))):
        return SpamViolation(blocked=False)

    if chat_id in set(_to_int_list(rules.get("exception_chat_ids", []))):
        return SpamViolation(blocked=False)

    text = message.text or message.caption or ""
    text_norm = _normalize_text(text)

    if rules["banned_accounts"]:
        banned_user_ids = set(_to_int_list(rules.get("banned_user_ids", [])))
        if user_id in banned_user_ids:
            return SpamViolation(blocked=True, rule="banned_account", detail="user in banned list")

    if rules["clear_commands"] and text_norm.startswith("/"):
        return SpamViolation(blocked=True, rule="command", detail="command message")

    if rules["block_channel_alias"] and message.sender_chat is not None:
        return SpamViolation(blocked=True, rule="channel_alias", detail=f"sender_chat={message.sender_chat.id}")

    if rules["block_forwards"]:
        blocked_chat_ids = set(_to_int_list(rules.get("blocked_forward_chat_ids", [])))
        blocked_user_ids = set(_to_int_list(rules.get("blocked_forward_user_ids", [])))
        f_chat_id, f_user_id = _forward_source_ids(message)
        if (f_chat_id is not None and f_chat_id in blocked_chat_ids) or (
            f_user_id is not None and f_user_id in blocked_user_ids
        ):
            return SpamViolation(
                blocked=True,
                rule="forward_source",
                detail=f"forward_chat_id={f_chat_id},forward_user_id={f_user_id}",
            )

    if rules["block_mentions"]:
        blocked_mention_ids = set(_to_int_list(rules.get("blocked_mention_ids", [])))
        mentioned = _extract_mentioned_ids(message)
        matched = mentioned & blocked_mention_ids
        if matched:
            return SpamViolation(blocked=True, rule="mention_target", detail=f"matched={sorted(matched)}")

    if text_norm:
        if rules["block_links"] and URL_RE.search(text_norm):
            return SpamViolation(blocked=True, rule="link", detail="url detected")

        if rules["block_links"]:
            blacklist = [str(x).lower() for x in rules.get("link_blacklist", []) if str(x).strip()]
            if any(domain in text_norm for domain in blacklist):
                return SpamViolation(blocked=True, rule="link_blacklist", detail="blacklist domain matched")

        if rules["block_eth_address"] and ETH_RE.search(text_norm):
            return SpamViolation(blocked=True, rule="eth_address", detail="eth address detected")

        if rules["global_ads"] and _contains_ad_keyword(text_norm):
            return SpamViolation(blocked=True, rule="ads", detail="ad keyword matched")

        if rules["ai_text"] and _looks_like_text_spam(text_norm):
            return SpamViolation(blocked=True, rule="ai_text_spam", detail="heuristic spam score matched")

    if rules["ai_image_ads"] and _message_has_media(message):
        file_name = ""
        if message.document is not None:
            file_name = message.document.file_name or ""
        signal_text = f"{text_norm} {file_name.lower()}".strip()
        if _contains_ad_keyword(signal_text) or URL_RE.search(signal_text):
            return SpamViolation(blocked=True, rule="image_ads", detail="media ad signal matched")

    if rules["block_long_content"]:
        max_len = int(rules["message_max_length"])
        name_max_len = int(rules["name_max_length"])
        if len(text) > max_len:
            return SpamViolation(blocked=True, rule="long_message", detail=f"len={len(text)},max={max_len}")
        if _display_name_len(message) > name_max_len:
            return SpamViolation(
                blocked=True,
                rule="long_name",
                detail=f"name_len={_display_name_len(message)},max={name_max_len}",
            )

    if rules["flood_attack"] and text_norm:
        repeated, ids, detail = await tracker.check_repeat(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message.message_id,
            text_norm=text_norm,
            max_messages=settings.anti_spam_repeat_messages,
            time_window_seconds=settings.anti_spam_repeat_seconds,
        )
        if repeated:
            return SpamViolation(
                blocked=True,
                rule="repeat_flood",
                detail=detail,
                message_ids_to_delete=ids,
            )

    return SpamViolation(blocked=False)
