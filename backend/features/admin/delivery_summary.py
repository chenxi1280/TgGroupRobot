"""Read execution facts without creating occurrences, retrying or sending messages."""
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from backend.platform.db.schema.models.automation import AdRotationHistory
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog
from backend.platform.db.schema.models.chat import TgChat
from backend.shared.time_helper import format_timestamp

STATUS_LABELS = {
    "pending": "等待执行", "processing": "执行中", "retryable_failed": "失败，等待重试",
    "succeeded": "已成功发送", "permanent_failed": "失败，需要处理",
    "uncertain": "结果未知，待核实", "cancelled": "已取消",
}
ERROR_LABELS = {
    "telegram_forbidden": "机器人权限不足或目标不可访问",
    "telegram_bad_request": "Telegram 拒绝请求，请检查内容和配置",
    "retry_after": "Telegram 限流", "network_error": "网络异常",
    "telegram_retry_after": "Telegram 限流",
    "telegram_network_unknown": "网络中断，发送结果未知",
    "telegram_result_unknown": "Telegram 返回不明确，发送结果未知",
    "unknown_after_send": "发送结果未知，需要核实远端事实",
}


async def _latest(session, model, *, chat_id: int, keys: list, key_column, successful: bool):
    stmt = select(model, func.row_number().over(
        partition_by=key_column, order_by=model.id.desc(),
    ).label("position")).where(model.chat_id == chat_id, key_column.in_(keys))
    if successful:
        stmt = stmt.where(model.status == "succeeded")
    ranked = stmt.subquery()
    entity = aliased(model, ranked)
    result = await session.execute(select(entity).where(ranked.c.position == 1))
    return list(result.scalars())


async def delivery_summaries(session, feature: str, *, chat_id: int, items: list):
    if feature not in {"scheduled", "ads"} or not items:
        return {}
    model = ScheduledMessageLog if feature == "scheduled" else AdRotationHistory
    field = "task_id" if feature == "scheduled" else "campaign_id"
    keys = [item.task_id if feature == "scheduled" else item.id for item in items]
    latest = await _latest(session, model, chat_id=chat_id, keys=keys, key_column=getattr(model, field), successful=False)
    success = await _latest(session, model, chat_id=chat_id, keys=keys, key_column=getattr(model, field), successful=True)
    latest_by_key = {getattr(row, field): row for row in latest}
    success_by_key = {getattr(row, field): row for row in success}
    chat=await session.get(TgChat,chat_id)
    return {key: format_delivery_summary(latest_by_key.get(key), success_by_key.get(key),
        chat_type=getattr(chat,'type',None),username=getattr(chat,'username',None)) for key in keys}


def _time(value) -> str:
    return format_timestamp(value.timestamp() if hasattr(value, "timestamp") else value) if value else "未知"


def format_delivery_summary(latest, success, *, chat_type=None, username=None) -> str:
    last_success = _time(success.sent_at) if success is not None else "未知/无成功记录"
    if latest is None:
        return f"最近成功：{last_success}\n最近执行：暂无执行记录"
    when = latest.completed_at or latest.send_started_at or getattr(latest, "created_at", None) or latest.scheduled_for
    label = STATUS_LABELS.get(latest.status, "未知状态，请查看历史")
    result = f"最近成功：{last_success}\n最近执行：{label} · {_time(when)}"
    if latest.status == "retryable_failed":
        result += f"\n重试计划：{_time(latest.next_retry_at)}"
    if latest.status in {"retryable_failed", "permanent_failed", "uncertain"}:
        reason = ERROR_LABELS.get(latest.error_code, "执行异常，请在历史查看详情")
        result += f"\n原因：{reason}"
    link=message_link(getattr(success,'chat_id',None),getattr(success,'message_id',None),chat_type=chat_type,username=username)
    return result + _action_summary(latest) + (f'\n最近成功消息：{link}' if link else '')


def message_link(chat_id, message_id, *, chat_type=None, username=None):
    if chat_type not in {'supergroup','channel'}:
        return None
    if not isinstance(message_id,int) or message_id <= 0:
        return None
    if username:
        return f'https://t.me/{username}/{message_id}'
    value=str(chat_id)
    if not value.startswith('-100') or not value[4:].isdigit() or not int(value[4:]):
        return None
    return f'https://t.me/c/{value[4:]}/{message_id}'


def _action_summary(latest) -> str:
    actions = getattr(latest, "post_actions", None) or {}
    messages=_action_messages(actions)
    if messages:
        return '\n'+'\n'.join(messages)
    if latest.status == "succeeded" and not actions:
        return "\n附加操作：历史未记录，不能确认"
    return ""


def _action_messages(actions):
    labels = {"pin": "置顶", "delete_previous": "删除旧消息", "unpin_previous": "取消旧置顶",'delete_delay':'延迟删除'}
    failures = [label for key, label in labels.items() if actions.get(key) == "failed"]
    messages=[]
    if failures:
        messages.append("附加操作失败：" + "、".join(failures) + "（仅恢复附加动作）")
    outstanding=[label for key,label in labels.items() if actions.get(key) in {'pending','waiting','processing','uncertain'}]
    if outstanding:
        messages.append('附加操作待处理/核实：'+'、'.join(outstanding))
    return messages
