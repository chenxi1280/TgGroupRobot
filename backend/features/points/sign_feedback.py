"""Configurable sign-in feedback; counts use timestamped facts in the business day."""
import datetime as dt
import string
from sqlalchemy import func, select

from backend.platform.db.schema.models.points import SignInLog
from backend.shared.services.module_config_service import get_module_config
from backend.shared.time_helper import LOCAL_TIMEZONE

ALLOWED_FIELDS = {"points", "balance", "days", "bonus", "total", "position"}
MAX_TEMPLATE_LENGTH = 800
MAX_DELETE_SECONDS = 86400


def validate_template(value: str) -> str:
    if not value or len(value) > MAX_TEMPLATE_LENGTH:
        raise ValueError("签到文案需为 1—800 字。")
    for _, field, spec, conversion in string.Formatter().parse(value):
        if field is not None and (field not in ALLOWED_FIELDS or spec or conversion):
            raise ValueError("只支持 {points} {balance} {days} {bonus} {total} {position}，不支持格式或属性表达式。")
    return value


async def feedback_text(session, settings, *, user_id: int, result, original: str):
    config = get_module_config(settings, "sign_feedback")
    if not config or not result.success:
        return original
    now = dt.datetime.now(dt.UTC)
    start = dt.datetime.combine(now.astimezone(LOCAL_TIMEZONE).date(), dt.time.min, tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    records = select(SignInLog).where(SignInLog.chat_id == settings.chat_id,
        SignInLog.created_at >= start, SignInLog.created_at < start + dt.timedelta(days=1))
    selected = records.subquery()
    total = await session.scalar(select(func.count(func.distinct(selected.c.user_id))))
    mine = await session.scalar(records.where(SignInLog.user_id == user_id).order_by(SignInLog.created_at, SignInLog.id).limit(1))
    position = 0
    if mine is not None:
        preceding = records.where(
            (SignInLog.created_at < mine.created_at) | ((SignInLog.created_at == mine.created_at) & (SignInLog.id <= mine.id)),
        ).subquery()
        position = await session.scalar(select(func.count(func.distinct(preceding.c.user_id))))
    values = dict(points=settings.sign_points, balance=result.balance, days=result.consecutive_days,
        bonus=result.bonus_points, total=total, position=position)
    template = config.get("template")
    text = validate_template(template).format_map(values) if template else original
    if config.get("show_count"):
        text += f"\n今日有效签到人数：{total}"
    if config.get("show_rank"):
        text += f"\n今日签到名次：{position}"
    return text


def schedule_feedback_delete(context, settings, message):
    seconds = get_module_config(settings, "sign_feedback").get("delete_seconds", 0)
    if isinstance(seconds, int) and 0 < seconds <= MAX_DELETE_SECONDS:
        from backend.features.group_ops.group_hooks.common import _schedule_message_delete
        _schedule_message_delete(context, message, seconds, name="points.sign_feedback_delete")


async def reply_with_feedback(update, context, *, db, settings, result, original: str):
    async with db.session_factory() as session:
        text = await feedback_text(session, settings, user_id=update.effective_user.id, result=result, original=original)
    sent = await update.effective_message.reply_text(text)
    schedule_feedback_delete(context, settings, sent)
