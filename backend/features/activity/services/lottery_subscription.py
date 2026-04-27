from __future__ import annotations

import re
from urllib.parse import urlparse

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.group_ops.group_hooks.control_force_subscribe import (
    _force_subscribe_label_from_chat,
    _force_subscribe_target_fallback_label,
    _force_subscribe_target_url,
    _is_force_subscribe_member,
    _normalize_force_subscribe_target,
)

log = structlog.get_logger(__name__)

LOTTERY_SUBSCRIBE_CHECK_MODE_ALL = "all"


def _split_target_items(text: str) -> list[str]:
    normalized = (text or "").replace("，", ",").replace("、", ",").replace("；", ";")
    return [item.strip() for item in re.split(r"[\n,;]+", normalized) if item.strip()]


def _valid_click_url(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "www.t.me", "telegram.me"}:
        return None
    if not parsed.path.strip("/"):
        return None
    return raw


def _target_key(target: str | int) -> str:
    return str(target).lower() if isinstance(target, str) else str(target)


def parse_lottery_subscribe_targets(text: str) -> list[dict]:
    targets: list[dict] = []
    seen: set[str] = set()
    for item in _split_target_items(text):
        if "|" in item:
            raw_target, raw_url = item.split("|", 1)
            explicit_url = _valid_click_url(raw_url)
        else:
            raw_target, explicit_url = item, None

        normalized_target = _normalize_force_subscribe_target(raw_target)
        if normalized_target is None:
            raise ValueError(f"关注目标格式无法识别：{item}")
        key = _target_key(normalized_target)
        if key in seen:
            continue
        seen.add(key)
        url = explicit_url or _force_subscribe_target_url(raw_target)
        label = _force_subscribe_target_fallback_label(normalized_target)
        targets.append({"target": normalized_target, "label": label, "url": url})
    if not targets:
        raise ValueError("强制订阅抽奖必须填写关注目标，格式如：@channel")
    return targets


def get_lottery_subscribe_targets(rules: dict | None) -> list[dict]:
    raw_targets = (rules or {}).get("subscribe_targets") or []
    targets: list[dict] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        target = _normalize_force_subscribe_target(item.get("target"))
        if target is None:
            continue
        url = _valid_click_url(item.get("url")) or _force_subscribe_target_url(target)
        targets.append(
            {
                "target": target,
                "label": str(item.get("label") or _force_subscribe_target_fallback_label(target)).strip(),
                "url": url,
            }
        )
    return targets


def requires_lottery_subscribe(lottery) -> bool:
    rules = getattr(lottery, "qualification_rules", None) or {}
    return bool(
        getattr(lottery, "lottery_type", None) == "subscribe"
        or rules.get("requires_lottery_subscribe")
        or rules.get("requires_force_subscribe")
    )


def format_lottery_subscribe_targets(targets: list[dict]) -> str:
    labels = []
    for item in targets:
        label = str(item.get("label") or item.get("target") or "").strip()
        if label:
            labels.append(label)
    return "、".join(labels) if labels else "指定频道/群组"


def build_lottery_subscribe_markup(targets: list[dict]) -> InlineKeyboardMarkup | None:
    buttons: list[InlineKeyboardButton] = []
    for item in targets:
        url = _valid_click_url(item.get("url")) or _force_subscribe_target_url(item.get("target"))
        if not url:
            continue
        label = str(item.get("label") or item.get("target") or "关注频道/群组").strip()[:64]
        buttons.append(InlineKeyboardButton(label, url=url))
    return InlineKeyboardMarkup([[button] for button in buttons]) if buttons else None


async def validate_lottery_subscribe_targets(
    context: ContextTypes.DEFAULT_TYPE,
    targets: list[dict],
) -> list[dict]:
    if not targets:
        raise ValueError("强制订阅抽奖必须填写关注目标。")
    bot = getattr(context, "bot", None)
    if bot is None or not hasattr(bot, "get_chat"):
        raise ValueError("无法校验关注目标：Bot 不可用。")

    validated: list[dict] = []
    for item in targets:
        target = _normalize_force_subscribe_target(item.get("target"))
        if target is None:
            raise ValueError(f"关注目标格式无法识别：{item.get('target')}")
        try:
            target_chat = await bot.get_chat(chat_id=target)
        except Exception as exc:
            raise ValueError(f"Bot 无法访问关注目标 {target}，请确认已加入该频道/群组并有权限查询成员。") from exc

        chat_type = str(target_chat.type or "").lower()
        if chat_type and chat_type not in {"channel", "group", "supergroup"}:
            raise ValueError(f"关注目标 {target} 不是频道或群组。")

        bot_id = getattr(bot, "id", None)
        if bot_id is not None and hasattr(bot, "get_chat_member"):
            try:
                bot_member = await bot.get_chat_member(chat_id=target, user_id=bot_id)
            except Exception as exc:
                raise ValueError(f"Bot 无法在关注目标 {target} 查询成员状态，请先把 Bot 加为管理员。") from exc
            bot_status = getattr(bot_member, "status", None)
            if bot_status not in {"administrator", "creator"}:
                raise ValueError(f"Bot 需要是关注目标 {target} 的管理员，才能校验成员关注状态。")

        fallback = str(item.get("label") or _force_subscribe_target_fallback_label(target)).strip()
        label = _force_subscribe_label_from_chat(target_chat, fallback)
        url = _valid_click_url(item.get("url")) or _force_subscribe_target_url(target, target_chat=target_chat)
        if not url:
            raise ValueError(f"关注目标 {label} 无法生成关注按钮；私有群/频道请使用 -100...|https://t.me/+invite 格式。")
        validated.append({"target": target, "label": label, "url": url})
    return validated


async def check_lottery_subscribe_membership(
    context: ContextTypes.DEFAULT_TYPE,
    targets: list[dict],
    user_id: int,
    *,
    check_mode: str = LOTTERY_SUBSCRIBE_CHECK_MODE_ALL,
) -> tuple[bool, str | None]:
    if not targets:
        return False, "本抽奖缺少订阅目标，请联系管理员重新发起强制订阅抽奖。"

    subscribed_results: list[bool] = []
    for item in targets:
        target = _normalize_force_subscribe_target(item.get("target"))
        if target is None:
            subscribed_results.append(False)
            continue
        try:
            member = await context.bot.get_chat_member(chat_id=target, user_id=user_id)
            subscribed_results.append(_is_force_subscribe_member(member))
        except Exception as exc:
            subscribed_results.append(False)
            log.warning("lottery_subscribe_check_failed", target=target, user_id=user_id, error=str(exc))

    subscribed = all(subscribed_results) if check_mode == LOTTERY_SUBSCRIBE_CHECK_MODE_ALL else any(subscribed_results)
    if subscribed:
        return True, None
    return False, f"请先关注本抽奖要求的频道/群组：{format_lottery_subscribe_targets(targets)}。关注后回到本抽奖重新点击参与。"


async def filter_lottery_subscribed_user_ids(
    context: ContextTypes.DEFAULT_TYPE,
    targets: list[dict],
    user_ids: list[int] | set[int],
    *,
    check_mode: str = LOTTERY_SUBSCRIBE_CHECK_MODE_ALL,
) -> set[int]:
    eligible: set[int] = set()
    for user_id in sorted({int(user_id) for user_id in user_ids if int(user_id) > 0}):
        allowed, _reason = await check_lottery_subscribe_membership(
            context,
            targets,
            user_id,
            check_mode=check_mode,
        )
        if allowed:
            eligible.add(user_id)
    return eligible
