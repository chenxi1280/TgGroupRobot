from __future__ import annotations

import asyncio
import copy
import datetime as dt
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import structlog
from telegram import Bot, ChatPermissions, Message


log = structlog.get_logger(__name__)

# URL / 地址 / 广告特征
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
}


@dataclass
class SpamViolation:
    blocked: bool
    rule: str = ""
    detail: str = ""
    message_ids_to_delete: list[int] = field(default_factory=list)


@dataclass
class SpamMessageRecord:
    at: dt.datetime
    text_norm: str
    message_id: int


class AntiSpamTracker:
    """反垃圾重复消息追踪器（内存实现）"""

    def __init__(self) -> None:
        self._records: dict[tuple[int, int], deque[SpamMessageRecord]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_repeat(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        text_norm: str,
        max_messages: int,
        time_window_seconds: int,
    ) -> tuple[bool, list[int], str]:
        if not text_norm:
            return False, [], ""

        now = dt.datetime.now(dt.UTC)
        cutoff = now - dt.timedelta(seconds=max(time_window_seconds, 1))
        key = (chat_id, user_id)

        async with self._lock:
            queue = self._records[key]

            while queue and queue[0].at < cutoff:
                queue.popleft()

            queue.append(SpamMessageRecord(at=now, text_norm=text_norm, message_id=message_id))

            similar: list[SpamMessageRecord] = []
            for item in queue:
                if item.text_norm == text_norm:
                    similar.append(item)
                    continue
                if SequenceMatcher(None, item.text_norm, text_norm).ratio() >= 0.92:
                    similar.append(item)

            if len(similar) >= max(max_messages, 2):
                ids = [item.message_id for item in similar]
                return True, ids, f"repeat_count={len(similar)}"

            return False, [], ""

    async def cleanup_old_records(self, max_age_seconds: int = 600) -> None:
        now = dt.datetime.now(dt.UTC)
        cutoff = now - dt.timedelta(seconds=max_age_seconds)

        async with self._lock:
            to_remove: list[tuple[int, int]] = []
            for key, queue in self._records.items():
                while queue and queue[0].at < cutoff:
                    queue.popleft()
                if not queue:
                    to_remove.append(key)

            for key in to_remove:
                self._records.pop(key, None)


_tracker = AntiSpamTracker()


def get_antispam_tracker() -> AntiSpamTracker:
    return _tracker


def get_antispam_rules(settings) -> dict[str, object]:
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
    settings,
    message: Message,
    chat_id: int,
    user_id: int,
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
        repeated, ids, detail = await _tracker.check_repeat(
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


async def execute_spam_punishment(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action: str,
    mute_duration: int,
    message_ids: list[int],
) -> bool:
    try:
        for message_id in sorted(set(message_ids)):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                log.warning("spam_delete_message_failed", chat_id=chat_id, message_id=message_id, error=str(e))

        if action == "delete":
            return True

        if action == "mute":
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_manage_topics=False,
                ),
                until_date=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=max(mute_duration, 1)),
            )
            return True

        if action == "ban":
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            return True

    except Exception as e:
        log.warning(
            "spam_punishment_failed",
            chat_id=chat_id,
            user_id=user_id,
            action=action,
            error=str(e),
        )
        return False

    return False


async def anti_spam_cleanup_job() -> None:
    await _tracker.cleanup_old_records(max_age_seconds=600)


def _to_int_list(values: list[object]) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result
