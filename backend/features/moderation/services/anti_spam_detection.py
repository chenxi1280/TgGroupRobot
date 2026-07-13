from __future__ import annotations

import re
from dataclasses import dataclass

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

TEXT_SPAM_SCORE_THRESHOLD = 3


@dataclass(frozen=True)
class SpamDetectionContext:
    rules: dict[str, object]
    message: Message
    chat_id: int
    user_id: int
    text: str
    text_norm: str


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
    return score >= TEXT_SPAM_SCORE_THRESHOLD


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


def _detect_account_or_command(ctx: SpamDetectionContext) -> SpamViolation | None:
    if ctx.rules["banned_accounts"]:
        banned_user_ids = set(_to_int_list(ctx.rules.get("banned_user_ids", [])))
        if ctx.user_id in banned_user_ids:
            return SpamViolation(blocked=True, rule="banned_account", detail="user in banned list")
    if ctx.rules["clear_commands"] and ctx.text_norm.startswith("/"):
        return SpamViolation(blocked=True, rule="command", detail="command message")
    if ctx.rules["block_channel_alias"] and ctx.message.sender_chat is not None:
        detail = f"sender_chat={ctx.message.sender_chat.id}"
        return SpamViolation(blocked=True, rule="channel_alias", detail=detail)
    return None


def _detect_forward_or_mention(ctx: SpamDetectionContext) -> SpamViolation | None:
    if ctx.rules["block_forwards"]:
        blocked_chat_ids = set(_to_int_list(ctx.rules.get("blocked_forward_chat_ids", [])))
        blocked_user_ids = set(_to_int_list(ctx.rules.get("blocked_forward_user_ids", [])))
        forward_chat_id, forward_user_id = _forward_source_ids(ctx.message)
        blocked_source = forward_chat_id in blocked_chat_ids or forward_user_id in blocked_user_ids
        if blocked_source:
            detail = f"forward_chat_id={forward_chat_id},forward_user_id={forward_user_id}"
            return SpamViolation(blocked=True, rule="forward_source", detail=detail)
    if ctx.rules["block_mentions"]:
        blocked_ids = set(_to_int_list(ctx.rules.get("blocked_mention_ids", [])))
        matched = _extract_mentioned_ids(ctx.message) & blocked_ids
        if matched:
            return SpamViolation(
                blocked=True,
                rule="mention_target",
                detail=f"matched={sorted(matched)}",
            )
    return None


def _detect_link_content(ctx: SpamDetectionContext) -> SpamViolation | None:
    if not ctx.text_norm:
        return None
    if ctx.rules["block_links"] and URL_RE.search(ctx.text_norm):
        return SpamViolation(blocked=True, rule="link", detail="url detected")
    if ctx.rules["block_links"]:
        blacklist = [
            str(value).lower()
            for value in ctx.rules.get("link_blacklist", [])
            if str(value).strip()
        ]
        if any(domain in ctx.text_norm for domain in blacklist):
            return SpamViolation(blocked=True, rule="link_blacklist", detail="blacklist domain matched")
    return None


def _detect_text_signals(ctx: SpamDetectionContext) -> SpamViolation | None:
    if not ctx.text_norm:
        return None
    if ctx.rules["block_eth_address"] and ETH_RE.search(ctx.text_norm):
        return SpamViolation(blocked=True, rule="eth_address", detail="eth address detected")
    if ctx.rules["global_ads"] and _contains_ad_keyword(ctx.text_norm):
        return SpamViolation(blocked=True, rule="ads", detail="ad keyword matched")
    if ctx.rules["ai_text"] and _looks_like_text_spam(ctx.text_norm):
        return SpamViolation(blocked=True, rule="ai_text_spam", detail="heuristic spam score matched")
    return None


def _detect_media_ad(ctx: SpamDetectionContext) -> SpamViolation | None:
    if not ctx.rules["ai_image_ads"] or not _message_has_media(ctx.message):
        return None
    file_name = ctx.message.document.file_name or "" if ctx.message.document is not None else ""
    signal_text = f"{ctx.text_norm} {file_name.lower()}".strip()
    if _contains_ad_keyword(signal_text) or URL_RE.search(signal_text):
        return SpamViolation(blocked=True, rule="image_ads", detail="media ad signal matched")
    return None


def _detect_long_content(ctx: SpamDetectionContext) -> SpamViolation | None:
    if not ctx.rules["block_long_content"]:
        return None
    max_len = int(ctx.rules["message_max_length"])
    if len(ctx.text) > max_len:
        return SpamViolation(
            blocked=True,
            rule="long_message",
            detail=f"len={len(ctx.text)},max={max_len}",
        )
    name_len = _display_name_len(ctx.message)
    name_max_len = int(ctx.rules["name_max_length"])
    if name_len > name_max_len:
        return SpamViolation(
            blocked=True,
            rule="long_name",
            detail=f"name_len={name_len},max={name_max_len}",
        )
    return None


async def _detect_repeat_flood(
    ctx: SpamDetectionContext,
    settings: ChatSettings,
    tracker: AntiSpamTracker,
) -> SpamViolation | None:
    if not ctx.rules["flood_attack"] or not ctx.text_norm:
        return None
    repeated, message_ids, detail = await tracker.check_repeat(
        chat_id=ctx.chat_id,
        user_id=ctx.user_id,
        message_id=ctx.message.message_id,
        text_norm=ctx.text_norm,
        max_messages=settings.anti_spam_repeat_messages,
        time_window_seconds=settings.anti_spam_repeat_seconds,
    )
    if not repeated:
        return None
    return SpamViolation(
        blocked=True,
        rule="repeat_flood",
        detail=detail,
        message_ids_to_delete=message_ids,
    )


async def detect_spam_violation(
    settings: ChatSettings,
    message: Message,
    chat_id: int,
    *, user_id: int,
    tracker: AntiSpamTracker,
) -> SpamViolation:
    rules = get_antispam_rules(settings)
    if user_id in set(_to_int_list(rules.get("exception_user_ids", []))):
        return SpamViolation(blocked=False)
    if chat_id in set(_to_int_list(rules.get("exception_chat_ids", []))):
        return SpamViolation(blocked=False)
    text = message.text or message.caption or ""
    ctx = SpamDetectionContext(
        rules=rules,
        message=message,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        text_norm=_normalize_text(text),
    )
    for detector in (
        _detect_account_or_command,
        _detect_forward_or_mention,
        _detect_link_content,
        _detect_text_signals,
        _detect_media_ad,
        _detect_long_content,
    ):
        violation = detector(ctx)
        if violation is not None:
            return violation
    repeat_violation = await _detect_repeat_flood(ctx, settings, tracker)
    if repeat_violation is not None:
        return repeat_violation
    return SpamViolation(blocked=False)
