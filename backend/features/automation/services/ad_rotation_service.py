from __future__ import annotations

import datetime as dt

import structlog
from telegram.ext import ContextTypes
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.automation.services.ad_rotation_formatting import (
    DEFAULT_DELETE_DELAY_SECONDS,
    DEFAULT_ROTATION_INTERVAL_SECONDS,
    MIN_ROTATION_INTERVAL_SECONDS,
    build_item_markup,
    compute_next_run_at,
    describe_delete_policy as describe_delete_policy,
    describe_rule_mode as describe_rule_mode,
    format_interval_seconds_label as format_interval_seconds_label,
    format_local_datetime as format_local_datetime,
    get_effective_item_count as get_effective_item_count,
    is_rotation_item_effective,
    parse_buttons_text as parse_buttons_text,
    parse_datetime_text as parse_datetime_text,
    parse_delay_seconds_text as parse_delay_seconds_text,
    parse_interval_hours_text as parse_interval_hours_text,
    parse_interval_minutes_text as parse_interval_minutes_text,
)
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService

RULE_MODES = {"send", "send_pin"}
DELETE_POLICIES = {"none", "delete_prev", "delete_prev_cycle", "delete_delay"}
UNSET = object()
log = structlog.get_logger(__name__)


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


def _validate_future_end_time(end_time: dt.datetime | None) -> None:
    if end_time is not None and end_time <= dt.datetime.now(dt.UTC):
        raise ValidationError("结束时间必须晚于当前时间")


def _update_item_content(
    item: AdCampaign,
    *,
    title: str | None,
    content: str | None,
    image_file_id: str | None,
    clear_image: bool,
    buttons: list | None,
) -> None:
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


def _update_item_window(
    item: AdCampaign,
    *,
    start_time: dt.datetime | None | object,
    end_time: dt.datetime | None | object,
    enabled: bool | None,
) -> None:
    if start_time is not UNSET:
        item.start_time = start_time
    if end_time is not UNSET:
        _validate_future_end_time(end_time)
        item.end_time = end_time
    _validate_item_window(item.start_time, item.end_time)
    if enabled is not None:
        item.enabled = enabled


def _shift_sort_orders(item: AdCampaign, items: list[AdCampaign], target_order: int) -> None:
    old_order = item.sort_order
    if target_order < old_order:
        for other in items:
            if other.id != item.id and target_order <= other.sort_order < old_order:
                other.sort_order += 1
        return
    for other in items:
        if other.id != item.id and old_order < other.sort_order <= target_order:
            other.sort_order -= 1


async def _reorder_rotation_item(session: AsyncSession, item: AdCampaign, sort_order: int | None) -> None:
    if sort_order is None:
        return
    items = await list_rotation_items(session, item.chat_id)
    target_order = max(1, min(int(sort_order), max(len(items), 1)))
    if target_order == item.sort_order:
        return
    _shift_sort_orders(item, items, target_order)
    item.sort_order = target_order
    await session.flush()
    await _normalize_sort_orders(session, item.chat_id)


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
    _update_item_content(
        item,
        title=title,
        content=content,
        image_file_id=image_file_id,
        clear_image=clear_image,
        buttons=buttons,
    )
    _update_item_window(item, start_time=start_time, end_time=end_time, enabled=enabled)
    await session.flush()
    await _reorder_rotation_item(session, item, sort_order)
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


def _set_rule_interval(rule: AdRotationRule, value: int) -> None:
    if value < MIN_ROTATION_INTERVAL_SECONDS:
        raise ValidationError("轮播间隔不能小于 1 分钟")
    rule.interval_seconds = value


def _set_rule_mode(rule: AdRotationRule, value: str) -> None:
    if value not in RULE_MODES:
        raise ValidationError("轮播方式无效")
    rule.mode = value


def _set_delete_policy(rule: AdRotationRule, value: str) -> None:
    if value not in DELETE_POLICIES:
        raise ValidationError("删除规则无效")
    rule.delete_policy = value


def _set_delete_delay(rule: AdRotationRule, value: int) -> None:
    if value <= 0:
        raise ValidationError("延迟删除秒数必须大于 0")
    rule.delete_delay_seconds = value


def _apply_rotation_rule_update(
    rule: AdRotationRule,
    *,
    enabled: bool | None,
    start_at: dt.datetime | None | object,
    interval_seconds: int | None,
    mode: str | None,
    delete_policy: str | None,
    delete_delay_seconds: int | None,
    unpin_previous: bool | None,
) -> None:
    if enabled is not None:
        rule.enabled = enabled
    if start_at is not UNSET:
        rule.start_at = start_at
    if interval_seconds is not None:
        _set_rule_interval(rule, interval_seconds)
    if mode is not None:
        _set_rule_mode(rule, mode)
    if delete_policy is not None:
        _set_delete_policy(rule, delete_policy)
    if delete_delay_seconds is not None:
        _set_delete_delay(rule, delete_delay_seconds)
    if unpin_previous is not None:
        rule.unpin_previous = unpin_previous


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
    _apply_rotation_rule_update(
        rule,
        enabled=enabled,
        start_at=start_at,
        interval_seconds=interval_seconds,
        mode=mode,
        delete_policy=delete_policy,
        delete_delay_seconds=delete_delay_seconds,
        unpin_previous=unpin_previous,
    )
    rule.next_run_at = compute_next_run_at(rule)
    await session.flush()
    return rule


def _integer_id_set(values) -> set[int]:
    return {int(value) for value in values or []}


def _effective_rotation_items(items: list[AdCampaign], excluded: set[int], current: dt.datetime) -> list[AdCampaign]:
    return [item for item in items if item.id not in excluded and is_rotation_item_effective(item, current)]


def _rotation_pool(rule: AdRotationRule, items: list[AdCampaign], current: dt.datetime) -> list[AdCampaign]:
    excluded = _integer_id_set(getattr(rule, "exclude_campaign_ids", []))
    available = _effective_rotation_items(items, excluded, current)
    top_ids = _integer_id_set(getattr(rule, "top_campaign_ids", []))
    if not top_ids:
        return available
    top_items = [item for item in available if item.id in top_ids]
    if not top_items:
        raise ValidationError("置顶轮播池没有可发送的有效条目")
    return top_items


def _rotation_index(available: list[AdCampaign], cursor: int) -> int:
    return next(
        (index for index, item in enumerate(available) if item.sort_order >= cursor),
        0,
    )


def select_next_rotation_item(
    rule: AdRotationRule,
    items: list[AdCampaign],
    *,
    now: dt.datetime | None = None,
) -> tuple[AdCampaign | None, int]:
    current = now or dt.datetime.now(dt.UTC)
    available = _rotation_pool(rule, items, current)
    if not available:
        return None, int(rule.current_order_cursor or 1)
    available.sort(key=lambda item: (item.sort_order, item.id))
    cursor = int(rule.current_order_cursor or 1)
    selected_index = _rotation_index(available, cursor)
    selected = available[selected_index]
    next_index = (selected_index + 1) % len(available)
    next_cursor = available[next_index].sort_order
    return selected, next_cursor


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
    from backend.features.automation.ad_delivery_executor import TelegramAdDeliveryExecutor
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    from backend.features.automation.ad_delivery_worker import AdDeliveryWorker, AdWorkerDependencies

    dependencies = AdWorkerDependencies(
        store=SqlAlchemyAdDeliveryStore(app.bot_data["db"]),
        executor=TelegramAdDeliveryExecutor(app),
        clock=lambda: dt.datetime.now(dt.UTC),
    )
    summary = await AdDeliveryWorker(dependencies).run()
    log.info(
        "ad_rotation_tick_finished",
        created=summary.created,
        planning_failed=summary.planning_failed,
        claimed=summary.claimed,
        succeeded=summary.succeeded,
        failed=summary.failed,
        recovered=summary.recovered,
    )
    return summary.succeeded
