from __future__ import annotations

import datetime as dt
import re
import structlog

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.core import TgUser
from backend.features.activity.services.lottery_winner_parsing import (
    RANDOM_WINNER_MARKERS,
    _split_preset_assignment_value,
    collect_winner_reference_values,
    extract_winner_usernames,
    parse_direct_winner_ids,
    validate_preset_winner_assignments,
)

log = structlog.get_logger(__name__)

LOTTERY_CREATE_STEPS = {
    "title",
    "prize_name",
    "subscribe_targets",
    "prize_quantity",
    "draw_param",
    "point_type",
    "participation_cost",
    "prize_action",
    "invite_requirement",
    "activity_requirement",
    "finalist_limit",
    "preset_confirm",
    "preset_winners",
}
PRESET_CLEAR_WORDS = {"无", "不设置", "跳过", "0", "可选", "留空"}


def _lottery_type_title(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
        "subscribe": "📣 强制订阅抽奖",
    }.get(lottery_type, "🎁 抽奖")


def _prize_slot_count(prizes: list[dict]) -> int:
    return sum(max(0, int(prize.get("quantity") or 0)) for prize in prizes)


def _format_local_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _default_deadline_text() -> str:
    local_tz = dt.timezone(dt.timedelta(hours=8))
    return (dt.datetime.now(local_tz) + dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")


def _parse_positive_int(value: str, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise ValueError(f"{field_name}必须是数字")
    if number <= 0:
        raise ValueError(f"{field_name}必须大于 0")
    return number


def _parse_non_negative_int(value: str, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise ValueError(f"{field_name}必须是数字")
    if number < 0:
        raise ValueError(f"{field_name}不能小于 0")
    return number


def _parse_future_time(value: str) -> dt.datetime:
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", value.strip())
    if not match:
        raise ValueError("开奖时间格式错误，请使用 YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    local_tz = dt.timezone(dt.timedelta(hours=8))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz).astimezone(dt.timezone.utc)
    if draw_time <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("开奖时间必须是未来时间")
    return draw_time


def _with_unique_user_id(user_ids: list[int], user_id: int | None) -> list[int]:
    if not isinstance(user_id, int) or user_id <= 0 or user_id in user_ids:
        return user_ids
    return [*user_ids, user_id]


def _message_entity_text(message: object, entity: object) -> str:
    parse_entity = getattr(message, "parse_entity", None)
    if callable(parse_entity):
        try:
            return parse_entity(entity)
        except Exception as exc:
            log.warning("lottery_entity_parse_failed", error=str(exc))
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    offset = int(getattr(entity, "offset", 0) or 0)
    length = int(getattr(entity, "length", 0) or 0)
    return text[offset : offset + length]


def _entity_type(entity: object) -> str:
    raw_type = getattr(entity, "type", None)
    return str(getattr(raw_type, "value", raw_type) or "")


def _entity_reference(message: object, entity: object) -> str | None:
    entity_type = _entity_type(entity)
    if entity_type == "text_link":
        return str(getattr(entity, "url", "") or "")
    if entity_type in {"mention", "url"}:
        return _message_entity_text(message, entity)
    return None


def _collect_entity_references(update: Update) -> tuple[list[int], list[str]]:
    message = getattr(update, "effective_message", None)
    winner_ids: list[int] = []
    usernames: list[str] = []
    for entity in getattr(message, "entities", None) or []:
        if _entity_type(entity) == "text_mention" and getattr(entity, "user", None) is not None:
            winner_ids = _with_unique_user_id(winner_ids, entity.user.id)
            continue
        reference = _entity_reference(message, entity)
        if reference is None:
            continue
        for user_id in parse_direct_winner_ids(reference):
            winner_ids = _with_unique_user_id(winner_ids, user_id)
        usernames.extend(extract_winner_usernames(reference))
    return winner_ids, usernames


def _merge_usernames(existing: list[str], added: list[str]) -> list[str]:
    merged = list(existing)
    normalized = {item.lower() for item in merged}
    for username in added:
        if username.lower() not in normalized:
            merged.append(username)
            normalized.add(username.lower())
    return merged


async def _resolve_username_to_user_id(session, context: ContextTypes.DEFAULT_TYPE, username: str) -> int | None:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        return None
    result = await session.execute(
        select(TgUser)
        .where(func.lower(TgUser.username) == normalized)
        .order_by(TgUser.updated_at.desc())
        .limit(1)
    )
    stored_user = result.scalars().first()
    if stored_user is not None:
        return int(stored_user.id)
    bot = getattr(context, "bot", None)
    if bot is None:
        return None
    try:
        target_chat = await bot.get_chat(f"@{normalized}")
    except Exception as exc:
        log.warning("lottery_target_username_lookup_failed", username=normalized, error=str(exc))
        return None
    target_id = target_chat.id
    if isinstance(target_id, int) and target_id > 0:
        return target_id
    return None


async def _resolve_usernames(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    usernames: list[str],
    *,
    resolve_username,
) -> tuple[list[int], list[str]]:
    winner_ids: list[int] = []
    unresolved: list[str] = []
    for username in usernames:
        user_id = await resolve_username(session, context, username)
        if user_id is None:
            unresolved.append(username)
        else:
            winner_ids = _with_unique_user_id(winner_ids, user_id)
    return winner_ids, unresolved


def _validate_resolved_winners(winner_ids: list[int], unresolved: list[str]) -> None:
    if unresolved:
        labels = "、".join(f"@{username}" for username in unresolved)
        raise ValueError(
            f"无法识别内定中奖人：{labels}。"
            "请确认用户已在群内出现过，或改发数字ID / tg://user?id= 链接"
        )
    if not winner_ids:
        raise ValueError("内定中奖人请发送数字ID、@用户名或用户链接，多个用户用逗号分隔")


async def _parse_preset_winner_ids_from_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, value: str,

    include_message_entities: bool = True,
    resolve_username=_resolve_username_to_user_id,
) -> list[int]:
    normalized = value.strip()
    if not normalized or normalized in PRESET_CLEAR_WORDS:
        return []

    winner_ids = parse_direct_winner_ids(normalized)
    usernames = extract_winner_usernames(normalized)
    if include_message_entities:
        entity_ids, entity_usernames = _collect_entity_references(update)
        for user_id in entity_ids:
            winner_ids = _with_unique_user_id(winner_ids, user_id)
        usernames = _merge_usernames(usernames, entity_usernames)
    resolved_ids, unresolved = await _resolve_usernames(
        session,
        context,
        usernames,
        resolve_username=resolve_username,
    )
    for user_id in resolved_ids:
        winner_ids = _with_unique_user_id(winner_ids, user_id)
    _validate_resolved_winners(winner_ids, unresolved)
    return winner_ids


def _requires_prize_assignment(prizes: list[dict]) -> bool:
    names = {
        str(prize.get("name") or "").strip()
        for prize in prizes
        if str(prize.get("name") or "").strip()
    }
    return len(names) > 1


def _validate_assignment_name(prize_name: str | None, *, required: bool) -> None:
    if required and prize_name is None:
        raise ValueError(
            "多个奖品时，请逐个奖品设置内定中奖人，格式：奖品名称: 用户；"
            "不指定的奖品请写：奖品名称: 随机"
        )


def _merge_assignment(
    assignments: list[dict],
    *,
    user_id: int,
    prize_name: str | None,
) -> list[dict]:
    if prize_name is None:
        return assignments
    if any(int(item.get("user_id") or 0) == user_id for item in assignments):
        return assignments
    return [*assignments, {"user_id": user_id, "prize_name": prize_name}]


async def _parse_winner_reference(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    value: str,
    prizes: list[dict],
    require_assignment: bool,
    include_message_entities: bool,
    resolve_username,
) -> tuple[list[int], str | None]:
    prize_name, winner_value = _split_preset_assignment_value(value, prizes)
    normalized = winner_value.strip()
    if normalized in PRESET_CLEAR_WORDS or normalized in RANDOM_WINNER_MARKERS:
        return [], prize_name
    _validate_assignment_name(prize_name, required=require_assignment)
    winner_ids = await _parse_preset_winner_ids_from_message(
        update,
        context,
        session,
        value=normalized,
        include_message_entities=include_message_entities and prize_name is None,
        resolve_username=resolve_username,
    )
    return winner_ids, prize_name


async def _resolve_preset_winner_refs_from_config_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, text: str,
    prizes: list[dict],
) -> tuple[list[int], list[dict]] | None:
    values = collect_winner_reference_values(text)
    if not values:
        return None
    return await _parse_preset_winner_refs_from_values(
        update,
        context,
        session,
        values=values,
        prizes=prizes,
        include_message_entities=False,
    )


async def _parse_preset_winner_refs_from_values(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, values: list[str],
    prizes: list[dict],

    include_message_entities: bool,
    resolve_username=_resolve_username_to_user_id,
) -> tuple[list[int], list[dict]]:
    merged_ids: list[int] = []
    assignments: list[dict] = []
    require_assignment = _requires_prize_assignment(prizes)
    for value in values:
        winner_ids, prize_name = await _parse_winner_reference(
            update,
            context,
            session,
            value=value,
            prizes=prizes,
            require_assignment=require_assignment,
            include_message_entities=include_message_entities,
            resolve_username=resolve_username,
        )
        for user_id in winner_ids:
            merged_ids = _with_unique_user_id(merged_ids, user_id)
            assignments = _merge_assignment(
                assignments,
                user_id=user_id,
                prize_name=prize_name,
            )
    validate_preset_winner_assignments(assignments, prizes)
    return merged_ids, assignments
