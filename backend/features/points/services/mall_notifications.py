from __future__ import annotations

import datetime as dt
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from backend.platform.db.schema.models.core import MallNotification, PointsMallOrder
from backend.shared.services.publish_service import PublishService


MAX_NOTIFICATION_ATTEMPTS = 5


async def _fallback(session, order):
    await session.execute(insert(MallNotification).values(
        order_id=order.order_id, recipient_id=order.chat_id, role="admin",
        assignment_version=order.assignment_version, status="pending", attempts=0,
        updated_at=dt.datetime.now(dt.UTC),
    ).on_conflict_do_nothing(constraint="uq_mall_notification_target"))


async def deliver_notification(db, context, notification_id: int):
    async with db.session_factory() as session:
        candidate = await session.get(MallNotification, notification_id)
        if candidate is None:
            return
        order = (await session.execute(select(PointsMallOrder).where(
            PointsMallOrder.order_id == candidate.order_id,
        ).with_for_update())).scalar_one()
        notification = (await session.execute(select(MallNotification).where(
            MallNotification.id == notification_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one()
        if notification.status not in {"pending", "retryable_failed"}:
            return
        if notification.next_retry_at and notification.next_retry_at > dt.datetime.now(dt.UTC):
            return
        if not await _validate_recipient(session, context, notification, order=order):
            return
        notification.status = "processing"
        notification.attempts += 1
        notification.updated_at = dt.datetime.now(dt.UTC)
        await session.commit()
        await _send_notification(context, notification, order)
        notification.updated_at = dt.datetime.now(dt.UTC)
        if notification.role != "admin" and notification.status not in {"succeeded", "retryable_failed"}:
            await _fallback(session, order)
        await session.commit()


async def dispatch_notifications(db, context):
    now = dt.datetime.now(dt.UTC)
    async with db.session_factory() as session:
        stale = (await session.execute(select(MallNotification.id, MallNotification.order_id).where(
            MallNotification.status == "processing", MallNotification.updated_at < now - dt.timedelta(minutes=2),
        ).limit(20))).all()
        for notification_id, order_id in stale:
            # Match claim/reassignment lock order: order first, notification second.
            order = (await session.execute(select(PointsMallOrder).where(
                PointsMallOrder.order_id == order_id).with_for_update(skip_locked=True))).scalar_one_or_none()
            if order is None:
                continue
            item = (await session.execute(select(MallNotification).where(
                MallNotification.id == notification_id).with_for_update()
                .execution_options(populate_existing=True))).scalar_one()
            if item.status != "processing" or item.updated_at >= now - dt.timedelta(minutes=2):
                continue
            item.status, item.last_error = "uncertain", "发送期间进程中断，结果待核实"
            if item.role != "admin":
                await _fallback(session, order)
        ids = list((await session.execute(select(MallNotification.id).where(
            MallNotification.status.in_(["pending", "retryable_failed"]),
            or_(MallNotification.next_retry_at.is_(None), MallNotification.next_retry_at <= now),
        ).order_by(MallNotification.id).limit(20))).scalars())
        await session.commit()
    for notification_id in ids:
        await deliver_notification(db, context, notification_id)


async def _validate_recipient(session, context, notification, *, order):
    if notification.role == "fulfiller":
        if (order.assignment_version != notification.assignment_version or
            order.fulfiller_user_id != notification.recipient_id or order.order_status != "created"):
            notification.status = "cancelled"
            await session.commit()
            return False
        try:
            member = await context.bot.get_chat_member(order.chat_id, notification.recipient_id)
            active = member.status not in {"left", "kicked"} and (member.status != "restricted" or member.is_member)
        except TelegramError:
            active = False
        if not active:
            notification.status, notification.last_error = "permanent_failed", "发放人员当前群身份不可确认，管理员需接管"
            await _fallback(session, order)
            await session.commit()
            return False
    return True


async def _send_notification(context, notification, order):
    if notification.role == "admin":
        text = f"订单 #{order.order_id} 待管理员处理。请打开受权限保护的订单页面。"
    else:
        heading = "兑换订单通知" if notification.role == "buyer" else "待发放任务通知（请人工处理）"
        text = (f"{heading}\\n订单 #{order.order_id}\\n商品：{order.product_snapshot.get('name', '历史商品')}\\n"
                f"扣分：{order.price_points}\\n状态：待发放\\n发放方式：人工发放")
    text = text.replace("\\n", "\n")
    callback = f"morder:detail:{order.chat_id}:{order.order_id}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("查看订单", callback_data=callback)]])
    try:
        result = await PublishService.send(context, chat_id=notification.recipient_id, text=text, reply_markup=markup)
    except RetryAfter as exc:
        notification.status = "retryable_failed" if notification.attempts < MAX_NOTIFICATION_ATTEMPTS else "permanent_failed"
        delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, dt.timedelta) else float(exc.retry_after)
        notification.next_retry_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=max(30, delay))
        notification.last_error = "发送受限"
    except (BadRequest, Forbidden):
        notification.status, notification.last_error = "permanent_failed", "通知被拒绝，请先私聊启动机器人并检查权限"
    except Exception:
        notification.status, notification.last_error = "uncertain", "通知结果待核实，不自动重发"
    else:
        notification.status, notification.message_id, notification.last_error = "succeeded", result.message_id, None
