"""Scoped date-field adapters; all writes use existing domain validation."""
from sqlalchemy import select

from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.shared.services.base import ValidationError


async def resource(session, state):
    data, kind = state.state_data, state.state_type
    target = data["target_chat_id"]
    if kind.startswith("sm_"):
        stmt = select(ScheduledMessageTask).where(
            ScheduledMessageTask.chat_id == target, ScheduledMessageTask.short_id == str(data["task_id"]))
    elif kind == "ads_rule_edit_start":
        stmt = select(AdRotationRule).where(AdRotationRule.chat_id == target)
    else:
        stmt = select(AdCampaign).where(AdCampaign.chat_id == target, AdCampaign.id == data["item_id"])
    row = (await session.execute(stmt.with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise ValidationError("对象已删除或不属于当前群，请退出后重新打开")
    return row


def date_version(row):
    fields = ("start_at", "end_at") if isinstance(row, ScheduledMessageTask) else (
        ("start_at",) if isinstance(row, AdRotationRule) else ("start_time", "end_time"))
    return [str(getattr(row, key)) for key in fields]


def scope_label(state):
    data = state.state_data
    label = {
        "sm_edit_start_at": "定时开始", "sm_edit_end_at": "定时结束",
        "ads_rule_edit_start": "轮播规则开始", "ads_item_edit_start": "广告开始",
        "ads_item_edit_end": "广告结束",
    }[state.state_type]
    entity = data.get("task_id") or data.get("item_id") or "全局规则"
    return f"群：{data['target_chat_id']} · 对象：{entity}\n字段：{label}"


async def apply_value(session, state, value):
    from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
    from backend.features.automation.services.ad_rotation_service import (
        parse_datetime_text, update_rotation_item, update_rotation_rule,
    )
    data, kind = state.state_data, state.state_type
    if kind.startswith("sm_"):
        method = (ScheduledMessageService.update_task_start_at if kind == "sm_edit_start_at"
                  else ScheduledMessageService.update_task_end_at)
        await method(session, data["task_id"], value)
    elif kind == "ads_rule_edit_start":
        await update_rotation_rule(session, data["target_chat_id"], start_at=parse_datetime_text(value))
    else:
        field = "start_time" if kind == "ads_item_edit_start" else "end_time"
        await update_rotation_item(session, data["item_id"], **{field: parse_datetime_text(value)})


async def return_to_source(update, context, *, state_type, data):
    if state_type.startswith("sm_"):
        from backend.features.automation.scheduled_message_handler import ScheduledMessageHandler
        await ScheduledMessageHandler().show_detail(update, context, data["target_chat_id"], task_id=data["task_id"])
    else:
        from backend.features.automation.ads_context import _ads_handler
        if state_type == "ads_rule_edit_start":
            await _ads_handler.show_rules(update, context, data["target_chat_id"])
        else:
            await _ads_handler.show_detail(update, context, data["target_chat_id"], item_id=data["item_id"])
