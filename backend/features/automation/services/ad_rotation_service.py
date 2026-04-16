from __future__ import annotations

import asyncio
import datetime as dt

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
from backend.shared.async_tasks import spawn_background_task
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService
from backend.shared.time_helper import LOCAL_TIMEZONE, parse_date_time_string
from backend.shared.ui.button_input import parse_button_rows

DEFAULT_ROTATION_INTERVAL_SECONDS = 2 * 3600
DEFAULT_DELETE_DELAY_SECONDS = 60
MIN_ROTATION_INTERVAL_SECONDS = 60
RULE_MODES = {"send", "send_pin"}
DELETE_POLICIES = {"none", "delete_prev", "delete_prev_cycle", "delete_delay"}
UNSET = object()
log = structlog.get_logger(__name__)


def format_local_datetime(value: dt.datetime | None, *, empty: str = "未设置") -> str:
    if value is None:
        return empty
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_text(value: str) -> dt.datetime | None:
    raw = (value or "").strip()
    if not raw or raw == "清空":
        return None
    timestamp = parse_date_time_string(raw)
    if timestamp is None:
        raise ValidationError("时间格式错误，请使用 YYYY-MM-DD HH:MM")
    return dt.datetime.fromtimestamp(timestamp, dt.UTC)


def parse_interval_minutes_text(value: str) -> int:
    raw = (value or "").strip()
    raw = raw.removesuffix("分钟").removesuffix("分").strip()
    if raw.endswith("小时"):
        raw_hours = raw.removesuffix("小时").strip()
        if not raw_hours.isdigit():
            raise ValidationError("请输入整数分钟，例如 90")
        minutes = int(raw_hours) * 60
    elif raw.endswith("天"):
        raw_days = raw.removesuffix("天").strip()
        if not raw_days.isdigit():
            raise ValidationError("请输入整数分钟，例如 90")
        minutes = int(raw_days) * 1440
    else:
        if not raw.isdigit():
            raise ValidationError("请输入整数分钟，例如 90")
        minutes = int(raw)
    seconds = minutes * 60
    if seconds < MIN_ROTATION_INTERVAL_SECONDS:
        raise ValidationError("轮播间隔不能小于 1 分钟")
    return seconds


def format_interval_seconds_label(interval_seconds: int | None) -> str:
    seconds = max(int(interval_seconds or DEFAULT_ROTATION_INTERVAL_SECONDS), MIN_ROTATION_INTERVAL_SECONDS)
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟"
    if minutes == 60:
        return "1小时"
    if minutes < 1440:
        hours = minutes // 60
        return f"{hours}小时"
    if minutes == 1440:
        return "1天"
    days = minutes // 1440
    return f"{days}天"


def parse_interval_hours_text(value: str) -> int:
    # 保留旧名称，兼容既有调用；当前统一按分钟输入解析。
    return parse_interval_minutes_text(value)


def parse_delay_seconds_text(value: str) -> int:
    raw = (value or "").strip().removesuffix("秒").strip()
    if not raw.isdigit():
        raise ValidationError("请输入整数秒数，例如 60")
    seconds = int(raw)
    if seconds <= 0:
        raise ValidationError("延迟删除秒数必须大于 0")
    return seconds


def parse_buttons_text(raw_text: str) -> list[list[dict[str, str]]]:
    return parse_button_rows(raw_text, allow_empty=False)


def build_item_markup(item: AdCampaign) -> InlineKeyboardMarkup | None:
    buttons = getattr(item, "buttons", None) or []
    if not buttons:
        return None
    try:
        normalized = ScheduledMessageService.normalize_buttons_config(buttons)
    except Exception:
        return None

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for row in normalized:
        button_row: list[InlineKeyboardButton] = []
        for button in row:
            text = str(button.get("text") or "").strip()
            url = str(button.get("url") or "").strip()
            if text and url:
                button_row.append(InlineKeyboardButton(text, url=url))
        if button_row:
            keyboard_rows.append(button_row)
    return InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None


def get_effective_item_count(items: list[AdCampaign], now: dt.datetime | None = None) -> int:
    current = now or dt.datetime.now(dt.UTC)
    return sum(1 for item in items if is_rotation_item_effective(item, current))


def describe_rule_mode(rule: AdRotationRule) -> str:
    return "轮流发送+置顶" if rule.mode == "send_pin" else "轮流发送"


def describe_delete_policy(rule: AdRotationRule) -> str:
    if rule.delete_policy == "none":
        return "不删除"
    if rule.delete_policy == "delete_prev":
        return "删除上一条轮播"
    if rule.delete_policy == "delete_delay":
        return f"延迟删除（{int(rule.delete_delay_seconds or DEFAULT_DELETE_DELAY_SECONDS)}秒）"
    return "删除上一轮相同消息"


def is_rotation_item_effective(item: AdCampaign, now: dt.datetime | None = None) -> bool:
    current = now or dt.datetime.now(dt.UTC)
    if not item.enabled:
        return False
    if item.start_time and item.start_time > current:
        return False
    if item.end_time and item.end_time <= current:
        return False
    return True


def compute_next_run_at(
    rule: AdRotationRule,
    *,
    now: dt.datetime | None = None,
    sent_at: dt.datetime | None = None,
) -> dt.datetime | None:
    if not rule.enabled:
        return None

    current = now or dt.datetime.now(dt.UTC)
    interval_seconds = max(int(rule.interval_seconds or DEFAULT_ROTATION_INTERVAL_SECONDS), MIN_ROTATION_INTERVAL_SECONDS)
    if sent_at is not None:
        return sent_at + dt.timedelta(seconds=interval_seconds)

    start_at = rule.start_at or current
    if start_at > current:
        return start_at
    if rule.last_sent_at:
        next_run = rule.last_sent_at + dt.timedelta(seconds=interval_seconds)
        return next_run if next_run > current else current
    return current


async def get_or_create_rotation_rule(session: AsyncSession, chat_id: int) -> AdRotationRule:
    stmt = select(AdRotationRule).where(AdRotationRule.chat_id == chat_id)
    result = await session.execute(stmt)
    rule = result.scalar_one_or_none()
    if rule is not None:
        return rule

    rule = AdRotationRule(
        chat_id=chat_id,
        enabled=False,
        interval_seconds=DEFAULT_ROTATION_INTERVAL_SECONDS,
        mode="send",
        delete_policy="delete_prev_cycle",
        delete_delay_seconds=DEFAULT_DELETE_DELAY_SECONDS,
        unpin_previous=True,
        current_order_cursor=1,
    )
    session.add(rule)
    await session.flush()
    return rule


async def list_rotation_items(session: AsyncSession, chat_id: int) -> list[AdCampaign]:
    stmt = (
        select(AdCampaign)
        .where(AdCampaign.chat_id == chat_id)
        .order_by(AdCampaign.sort_order.asc(), AdCampaign.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_rotation_item(session: AsyncSession, item_id: int) -> AdCampaign | None:
    stmt = select(AdCampaign).where(AdCampaign.id == item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _normalize_sort_orders(session: AsyncSession, chat_id: int) -> None:
    items = await list_rotation_items(session, chat_id)
    for index, item in enumerate(items, start=1):
        if item.sort_order != index:
            item.sort_order = index
    await session.flush()


async def _next_sort_order(session: AsyncSession, chat_id: int) -> int:
    stmt = select(func.max(AdCampaign.sort_order)).where(AdCampaign.chat_id == chat_id)
    result = await session.execute(stmt)
    current_max = result.scalar_one_or_none() or 0
    return int(current_max) + 1


async def create_rotation_item(
    session: AsyncSession,
    *,
    chat_id: int,
    created_by_user_id: int | None = None,
    title: str = "未命名轮播",
    content: str = "",
) -> AdCampaign:
    item = AdCampaign(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        title=title[:128] or "未命名轮播",
        content=content,
        enabled=True,
        has_image=False,
        buttons=[],
        sort_order=await _next_sort_order(session, chat_id),
        send_count=0,
        last_sent_cycle_no=0,
    )
    session.add(item)
    await session.flush()
    await get_or_create_rotation_rule(session, chat_id)
    return item


def _validate_item_window(start_time: dt.datetime | None, end_time: dt.datetime | None) -> None:
    if start_time is not None and end_time is not None and start_time >= end_time:
        raise ValidationError("开始时间必须早于结束时间")


async def update_rotation_item(
    session: AsyncSession,
    item_id: int,
    *,
    title: str | None = None,
    content: str | None = None,
    image_file_id: str | None = None,
    clear_image: bool = False,
    buttons: list | None = None,
    start_time: dt.datetime | None | object = UNSET,
    end_time: dt.datetime | None | object = UNSET,
    enabled: bool | None = None,
    sort_order: int | None = None,
) -> AdCampaign:
    item = await get_rotation_item(session, item_id)
    if item is None:
        raise ValidationError("轮播消息不存在")

    if title is not None:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValidationError("标题不能为空")
        item.title = normalized_title[:128]
    if content is not None:
        item.content = content.strip()
    if clear_image:
        item.image_file_id = None
        item.image_url = None
        item.has_image = False
    elif image_file_id is not None:
        item.image_file_id = image_file_id
        item.image_url = None
        item.has_image = bool(image_file_id)
    if buttons is not None:
        item.buttons = ScheduledMessageService.normalize_buttons_config(buttons)
    if start_time is not UNSET:
        item.start_time = start_time
    if end_time is not UNSET:
        item.end_time = end_time
    _validate_item_window(item.start_time, item.end_time)
    if enabled is not None:
        item.enabled = enabled
    await session.flush()

    if sort_order is not None:
        items = await list_rotation_items(session, item.chat_id)
        max_order = max(len(items), 1)
        target_order = max(1, min(int(sort_order), max_order))
        old_order = item.sort_order
        if target_order != old_order:
            if target_order < old_order:
                for other in items:
                    if other.id != item.id and target_order <= other.sort_order < old_order:
                        other.sort_order += 1
            else:
                for other in items:
                    if other.id != item.id and old_order < other.sort_order <= target_order:
                        other.sort_order -= 1
            item.sort_order = target_order
            await session.flush()
            await _normalize_sort_orders(session, item.chat_id)
    return item


async def toggle_rotation_item(session: AsyncSession, item_id: int) -> AdCampaign:
    item = await get_rotation_item(session, item_id)
    if item is None:
        raise ValidationError("轮播消息不存在")
    item.enabled = not item.enabled
    await session.flush()
    return item


async def delete_rotation_item(session: AsyncSession, chat_id: int, item_id: int) -> None:
    item = await get_rotation_item(session, item_id)
    if item is None or item.chat_id != chat_id:
        raise ValidationError("轮播消息不存在")
    await session.delete(item)
    await session.flush()
    await _normalize_sort_orders(session, chat_id)


async def cleanup_expired_rotation_items(session: AsyncSession, chat_id: int) -> int:
    now = dt.datetime.now(dt.UTC)
    items = await list_rotation_items(session, chat_id)
    deleted = 0
    for item in items:
        if item.end_time and item.end_time <= now:
            await session.delete(item)
            deleted += 1
    if deleted:
        await session.flush()
        await _normalize_sort_orders(session, chat_id)
    return deleted


async def update_rotation_rule(
    session: AsyncSession,
    chat_id: int,
    *,
    enabled: bool | None = None,
    start_at: dt.datetime | None | object = UNSET,
    interval_seconds: int | None = None,
    mode: str | None = None,
    delete_policy: str | None = None,
    delete_delay_seconds: int | None = None,
    unpin_previous: bool | None = None,
) -> AdRotationRule:
    rule = await get_or_create_rotation_rule(session, chat_id)
    if enabled is not None:
        rule.enabled = enabled
    if start_at is not UNSET:
        rule.start_at = start_at
    if interval_seconds is not None:
        if interval_seconds < MIN_ROTATION_INTERVAL_SECONDS:
            raise ValidationError("轮播间隔不能小于 1 分钟")
        rule.interval_seconds = interval_seconds
    if mode is not None:
        if mode not in RULE_MODES:
            raise ValidationError("轮播方式无效")
        rule.mode = mode
    if delete_policy is not None:
        if delete_policy not in DELETE_POLICIES:
            raise ValidationError("删除规则无效")
        rule.delete_policy = delete_policy
    if delete_delay_seconds is not None:
        if delete_delay_seconds <= 0:
            raise ValidationError("延迟删除秒数必须大于 0")
        rule.delete_delay_seconds = delete_delay_seconds
    if unpin_previous is not None:
        rule.unpin_previous = unpin_previous

    rule.next_run_at = compute_next_run_at(rule)
    await session.flush()
    return rule


def select_next_rotation_item(
    rule: AdRotationRule,
    items: list[AdCampaign],
    *,
    now: dt.datetime | None = None,
) -> tuple[AdCampaign | None, int]:
    current = now or dt.datetime.now(dt.UTC)
    available = [item for item in items if is_rotation_item_effective(item, current)]
    if not available:
        return None, int(rule.current_order_cursor or 1)

    available.sort(key=lambda item: (item.sort_order, item.id))
    cursor = int(rule.current_order_cursor or 1)

    selected_index = 0
    for index, item in enumerate(available):
        if item.sort_order >= cursor:
            selected_index = index
            break
    else:
        selected_index = 0

    selected = available[selected_index]
    next_index = (selected_index + 1) % len(available)
    next_cursor = available[next_index].sort_order
    return selected, next_cursor


async def _delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    try:
        await PublishService.delete(context, chat_id=chat_id, message_id=message_id)
    except Exception:
        return


async def _unpin_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    try:
        await PublishService.unpin(context, chat_id=chat_id, message_id=message_id)
    except Exception:
        return


async def _delete_later(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    delay_seconds: int,
) -> None:
    try:
        await asyncio.sleep(max(delay_seconds, 1))
    except asyncio.CancelledError:
        raise
    await _delete_message_safely(context, chat_id=chat_id, message_id=message_id)


async def send_rotation_item(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    item: AdCampaign,
):
    text = (item.content or "").strip() or item.title
    reply_markup = build_item_markup(item)
    if item.image_file_id:
        return await PublishService.send_photo(
            context,
            chat_id=chat_id,
            photo=item.image_file_id,
            caption=text,
            reply_markup=reply_markup,
        )
    return await PublishService.send(
        context,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )


async def preview_rotation_item(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    item: AdCampaign,
):
    return await send_rotation_item(context, chat_id=chat_id, item=item)


async def dispatch_due_rotation_rules(app) -> int:
    db = app.bot_data["db"]
    dispatched = 0
    now = dt.datetime.now(dt.UTC)

    async with db.session_factory() as session:
        stmt = (
            select(AdRotationRule)
            .where(
                AdRotationRule.enabled == True,
                or_(AdRotationRule.next_run_at.is_(None), AdRotationRule.next_run_at <= now),
            )
            .order_by(AdRotationRule.next_run_at.asc().nullsfirst())
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        rules = list(result.scalars().all())

        for rule in rules:
            try:
                handled = await _dispatch_one_rule(session, app, rule, now=now)
            except Exception as exc:
                log.exception("ad_rotation_dispatch_failed", chat_id=rule.chat_id, error=str(exc))
                rule.next_run_at = compute_next_run_at(rule, now=now, sent_at=now)
                handled = False
            if handled:
                dispatched += 1
            await session.commit()
    return dispatched


async def _dispatch_one_rule(
    session: AsyncSession,
    app,
    rule: AdRotationRule,
    *,
    now: dt.datetime,
) -> bool:
    items = await list_rotation_items(session, rule.chat_id)
    item, next_cursor = select_next_rotation_item(rule, items, now=now)

    if item is None:
        rule.next_run_at = compute_next_run_at(rule, now=now, sent_at=now)
        return False

    context = type("BotContext", (), {"bot": app.bot, "application": app})()

    if rule.delete_policy == "delete_prev":
        await _delete_message_safely(context, chat_id=rule.chat_id, message_id=rule.last_sent_message_id)
    elif rule.delete_policy == "delete_prev_cycle":
        await _delete_message_safely(context, chat_id=rule.chat_id, message_id=item.last_sent_message_id)

    if rule.mode == "send_pin" and rule.unpin_previous:
        await _unpin_message_safely(context, chat_id=rule.chat_id, message_id=rule.last_pinned_message_id)

    result = await send_rotation_item(context, chat_id=rule.chat_id, item=item)
    message_id = result.message_id

    if rule.mode == "send_pin" and message_id is not None:
        try:
            await PublishService.pin(context, chat_id=rule.chat_id, message_id=message_id)
            rule.last_pinned_message_id = message_id
        except Exception:
            rule.last_pinned_message_id = None
    else:
        rule.last_pinned_message_id = None

    if rule.delete_policy == "delete_delay" and message_id is not None:
        spawn_background_task(
            app,
            _delete_later(
                context,
                chat_id=rule.chat_id,
                message_id=message_id,
                delay_seconds=int(rule.delete_delay_seconds or DEFAULT_DELETE_DELAY_SECONDS),
            ),
            name="ad_rotation.delete_later",
        )

    item.last_sent_at = now
    item.last_sent_message_id = message_id
    item.last_sent_cycle_no = int(item.last_sent_cycle_no or 0) + 1
    item.send_count = int(item.send_count or 0) + 1

    rule.last_sent_at = now
    rule.last_sent_item_id = item.id
    rule.last_sent_message_id = message_id
    rule.current_order_cursor = next_cursor
    rule.next_run_at = compute_next_run_at(rule, now=now, sent_at=now)
    await session.flush()
    return True
