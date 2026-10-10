from __future__ import annotations
import datetime as dt
import hashlib
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from telegram.error import TelegramError
from backend.platform.db.schema.models.ui_feedback import UiFeedback
from backend.platform.runtime.request_scope import current_scope

log = structlog.get_logger(__name__)


async def retain_feedback(update, text):
    scope = current_scope()
    if scope is None or scope.user_id is None or not text:
        return
    db = scope.cache.get("feedback_db")
    if db is None:
        return
    token = hashlib.sha256(f"{scope.update_id}:{scope.user_id}:{text}".encode()).hexdigest()[:32]
    try:
        async with db.session_factory() as session:
            await session.execute(insert(UiFeedback).values(token=token, user_id=scope.user_id,
                text=text, status="pending", created_at=dt.datetime.now(dt.UTC)).on_conflict_do_nothing())
            await session.commit()
    except Exception:
        log.exception("retain_feedback_failed", feedback_id=token)


async def show_pending_feedback(update, context):
    if update.effective_chat.type != "private":
        return
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        records = (await session.execute(select(UiFeedback).where(UiFeedback.user_id == update.effective_user.id,
            UiFeedback.status == "pending").order_by(UiFeedback.created_at).limit(5))).scalars().all()
        for record in records:
            try:
                await _display_feedback(update, record)
            except TelegramError:
                break
            record.status = "shown"
        await session.commit()


async def _display_feedback(update, record):
    text = f"此前未能显示的操作结果（编号 {record.token[:8]}）：\n{record.text}"
    for start in range(0, len(text), 3500):
        await update.effective_message.reply_text(text[start:start+3500])
