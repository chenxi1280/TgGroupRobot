from __future__ import annotations

import datetime as dt
import secrets
from sqlalchemy import func, select, update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from backend.platform.db.schema.models.core import EditDraft, MallNotification, PointsMallOrder, PointsMallOrderLog
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.platform.telegram.errors import answer_callback_query_safely

CALLBACK_WITH_ORIGIN = 6
COMMAND_WITH_NOTE = 3
LOOKUP_ARGUMENTS = 2
MAX_NOTE_LENGTH = 2000

STATUS_NAMES = {"created": "待发放", "fulfilled": "已人工标记发放", "canceled": "已取消", "refunded": "已退款"}


async def _order_access(context, order, user_id):
    admin = await PermissionPolicyService.can_manage(context, order.chat_id, user_id)
    assigned = order.fulfiller_user_id == user_id and await _active_member(context, order.chat_id, user_id)
    return admin, assigned


async def _active_member(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status not in {"left", "kicked"} and (member.status != "restricted" or member.is_member)
    except TelegramError:
        return False


async def _page(update, text, rows):
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def order_callback(update, context):
    if not update.callback_query or not update.effective_user:
        return
    parts = (update.callback_query.data or "").split(":")
    if len(parts) not in {4, 6}:
        await answer_callback_query_safely(update, "订单入口已失效，请重新打开我的订单。", show_alert=True)
        return
    _, action, chat_token, value = parts[:4]
    try:
        chat_id = int(chat_token)
    except ValueError:
        return
    if update.effective_chat.type != "private":
        await _redirect_order_to_private(update, context, action=action, value=value)
        return
    if action == "search":
        await _page(update, "发送 /order 订单编号 查找订单，例如 /order 123。仅可查看自己购买、当前分配或有管理权限的订单。",
            [[InlineKeyboardButton("我的订单", callback_data="morder:mine:0:0")]])
        return
    user_id = update.effective_user.id
    db = context.application.bot_data["db"]
    back = _order_back_buttons(parts)
    async with db.session_factory() as session:
        if action in {"mine", "assigned"}:
            await _list_orders(update, context, session, action=action, value=value, user_id=user_id, back=back)
            return
        await _order_action(update, context, session, action=action, value=value, chat_id=chat_id, user_id=user_id, back=back)


async def deliver_command(update, context):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("请在私聊填写发放说明。")
        return
    args = await _deliver_arguments(update)
    if args is None:
        return
    user_id = update.effective_user.id
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        order = await session.get(PointsMallOrder, int(args[1]))
        if order is None or order.order_status != "created":
            await update.effective_message.reply_text("订单不存在或已处理。")
            return
        admin, assigned = await _order_access(context, order, user_id)
        if not (admin or assigned):
            await update.effective_message.reply_text("你当前无权发放此订单。")
            return
        note = args[2].strip()
        if len(note) > MAX_NOTE_LENGTH:
            await update.effective_message.reply_text("说明不能超过 2000 字。")
            return
        draft = EditDraft(token=secrets.token_hex(12), user_id=user_id, chat_id=order.chat_id,
            state_chat_id=user_id, state_type="mall_fulfillment_confirmation",
            state_data={"order_id": order.order_id, "note": note, "assignment_version": order.assignment_version},
            expires_at=dt.datetime.now(dt.UTC)+dt.timedelta(minutes=10))
        session.add(draft)
        await session.commit()
        await _page(update, f"确认人工标记发放订单 #{order.order_id}？\n说明：{note}\n此标记记录处理结果，不代表买家已确认收到。",
            [[InlineKeyboardButton("确认标记发放", callback_data=f"morder:confirm:{order.chat_id}:{draft.token}")],
             [InlineKeyboardButton("返回订单", callback_data=f"morder:detail:{order.chat_id}:{order.order_id}")]])


async def assign_command(update, context):
    args = await _assignment_arguments(update)
    if args is None:
        return
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        order = (await session.execute(select(PointsMallOrder).where(PointsMallOrder.order_id == int(args[1])).with_for_update())).scalar_one_or_none()
        if order is None or not await PermissionPolicyService.can_manage(context, order.chat_id, update.effective_user.id):
            await update.effective_message.reply_text("订单不存在或没有管理权限。")
            return
        if order.order_status != "created":
            await update.effective_message.reply_text("仅待发放订单可改派。")
            return
        target = int(args[2]) or None
        if target and not await _active_member(context, order.chat_id, target):
            await update.effective_message.reply_text("新人员必须是当前群成员。")
            return
        await _reassign_order(session, order, target=target, operator_user_id=update.effective_user.id)
    await update.effective_message.reply_text("已改派；尚未开始的旧通知已取消，已发送及待核实结果保留。")


def update_stmt(order_id):
    return update(MallNotification).where(MallNotification.order_id == order_id,
        MallNotification.role == "fulfiller", MallNotification.status.in_(["pending", "retryable_failed", "permanent_failed"])).values(status="cancelled")


async def show_order_lookup(update, context, raw_id):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("请私聊机器人发送 /order 订单编号。")
        return
    if not str(raw_id).isdigit():
        await update.effective_message.reply_text("请输入 /order 订单编号，例如 /order 123。")
        return
    async with context.application.bot_data["db"].session_factory() as session:
        order = await session.get(PointsMallOrder, int(raw_id))
        if order is None:
            await update.effective_message.reply_text("订单不存在或没有查看权限。")
            return
        admin, assigned = await _order_access(context, order, update.effective_user.id)
        if not (admin or assigned or order.buyer_user_id == update.effective_user.id):
            await update.effective_message.reply_text("订单不存在或没有查看权限。")
            return
        await update.effective_message.reply_text(f"订单 #{order.order_id} · {STATUS_NAMES.get(order.order_status, order.order_status)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("查看详情", callback_data=f"morder:detail:{order.chat_id}:{order.order_id}")]]))


async def order_command(update, context):
    args = (update.effective_message.text or "").split()
    await show_order_lookup(update, context, args[1] if len(args) == LOOKUP_ARGUMENTS else "")


async def _list_orders(update, context, session, *, action, value, user_id, back):
    predicate = PointsMallOrder.buyer_user_id == user_id if action == "mine" else (PointsMallOrder.fulfiller_user_id == user_id) & (PointsMallOrder.order_status == "created")
    total = await session.scalar(select(func.count()).select_from(PointsMallOrder).where(predicate))
    page = max(0, min(int(value) if value.isdigit() else 0, max(0, (total - 1)//8)))
    orders = list((await session.execute(select(PointsMallOrder).where(predicate).order_by(PointsMallOrder.order_id.desc()).offset(page*8).limit(8))).scalars())
    rows = []
    for order in orders:
        if action == "assigned" and not (await _order_access(context, order, user_id))[1]:
            continue
        rows.append([InlineKeyboardButton(f"#{order.order_id} · {STATUS_NAMES.get(order.order_status, order.order_status)}", callback_data=f"morder:detail:{order.chat_id}:{order.order_id}:{action}:{page}")])
    nav = []
    if page:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"morder:{action}:0:{page-1}"))
    if (page+1)*8 < total:
        nav.append(InlineKeyboardButton("下一页", callback_data=f"morder:{action}:0:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("按编号查找", callback_data="morder:search:0:0"), InlineKeyboardButton("刷新", callback_data=f"morder:{action}:0:{page}")])
    rows.append(back)
    await _page(update, f"订单列表，共 {total} 条，第 {page+1}/{max(1,(total+7)//8)} 页。\n所属群身份失效的发放入口已隐藏。", rows)
    return


async def _order_action(update, context, session, *, action, value, chat_id, user_id, back):
    if action == "confirm":
        draft = (await session.execute(select(EditDraft).where(EditDraft.token == value,
            EditDraft.user_id == user_id, EditDraft.chat_id == chat_id,
            EditDraft.state_type == "mall_fulfillment_confirmation").with_for_update())).scalar_one_or_none()
        if draft is None or draft.expires_at <= dt.datetime.now(dt.UTC):
            await _page(update, "确认不存在或已过期，请重新填写发放说明。", [back])
            return
        order_id = draft.state_data["order_id"]
    else:
        draft = None
        order_id = int(value) if value.isdigit() else 0
    order = await PointsExtendedService.get_order(session, chat_id, order_id)
    if order is None:
        await _page(update, "订单不存在。", [back])
        return
    admin, assigned = await _order_access(context, order, user_id)
    if not (admin or assigned or order.buyer_user_id == user_id):
        await _page(update, "无权查看或处理此订单。", [back])
        return
    if action == "confirm":
        return await _confirm_fulfillment(update, session, admin=admin, assigned=assigned, chat_id=chat_id, order_id=order_id, user_id=user_id, draft=draft, back=back)
    await _order_detail(update, session, order, admin=admin, assigned=assigned, back=back)


async def _order_detail(update, session, order, *, admin, assigned, back):
    order_id = order.order_id
    snapshot = order.product_snapshot or {}
    text = (f"订单 #{order.order_id}\n商品：{snapshot.get('name', '历史商品')}\n"
            f"扣分：{order.price_points}\n状态：{STATUS_NAMES.get(order.order_status, order.order_status)}\n"
            f"发放方式：人工发放\n发放说明：{order.fulfillment_note or '未填写'}")
    if admin or assigned:
        notifications = list((await session.execute(select(MallNotification).where(MallNotification.order_id == order_id))).scalars())
        roles = {"buyer": "买家", "fulfiller": "发放人员", "admin": "管理员"}
        statuses = {"pending": "待通知", "processing": "发送中", "succeeded": "已发送", "retryable_failed": "等待重试", "permanent_failed": "发送失败", "uncertain": "结果待核实", "cancelled": "已停止"}
        text += "\n通知状态：" + "；".join(f"{roles.get(n.role, n.role)}：{statuses.get(n.status, n.status)}" for n in notifications)
        if order.order_status == "created":
            text += f"\n\n私聊发送 /deliver {order_id} 发放说明，随后确认。"
            if admin:
                text += f"\n改派：/assign {order_id} 新人员ID（0 表示管理员接管）"
    await _page(update, text, [back])


async def _deliver_arguments(update):
    args = (update.effective_message.text or "").split(maxsplit=2)
    if len(args) != COMMAND_WITH_NOTE or not args[1].isdigit() or not args[2].strip():
        await update.effective_message.reply_text("格式：/deliver 订单编号 发放说明（可附交付凭据链接）")
        return
    return args


def _order_back_buttons(parts):
    back = [InlineKeyboardButton("我的订单", callback_data="morder:mine:0:0"), InlineKeyboardButton("待发放订单", callback_data="morder:assigned:0:0")]
    if len(parts) == CALLBACK_WITH_ORIGIN and parts[4] in {"mine", "assigned"} and parts[5].isdigit():
        back = [InlineKeyboardButton("返回原订单列表", callback_data=f"morder:{parts[4]}:0:{parts[5]}")]
    return back


async def _reassign_order(session, order, *, target, operator_user_id):
    previous = order.fulfiller_user_id
    order.fulfiller_user_id, order.assignment_version = target, order.assignment_version + 1
    await session.execute(update_stmt(order.order_id))
    session.add(MallNotification(order_id=order.order_id, recipient_id=target or order.chat_id,
        role="fulfiller" if target else "admin", assignment_version=order.assignment_version))
    session.add(PointsMallOrderLog(order_id=order.order_id, action="reassign", payload={
        "operator_user_id": operator_user_id, "previous": previous, "assigned": target,
        "assignment_version": order.assignment_version}))
    await session.commit()


async def _confirm_fulfillment(update, session, *, admin, assigned, chat_id, order_id, user_id, draft, back):
    if not (admin or assigned):
        await _page(update, "发放权限已失效，请联系群管理员。", [back])
        return
    success, message, order = await PointsExtendedService.fulfill_order(session, chat_id=chat_id,
        order_id=order_id, operator_user_id=user_id, note=draft.state_data["note"],
        assigned_only=not admin, assignment_version=draft.state_data["assignment_version"])
    await session.delete(draft)
    await session.commit()
    await _page(update, message, [[InlineKeyboardButton("查看订单", callback_data=f"morder:detail:{chat_id}:{order_id}")]])
    return


async def _redirect_order_to_private(update, context, *, action, value):
    payload = f"order_{value}" if action == "detail" and value.isdigit() else "orders"
    await _page(update, "请在机器人私聊中查看和处理订单。", [[InlineKeyboardButton("私聊查看订单", url=f"https://t.me/{context.bot.username}?start={payload}")]])
    return


async def _assignment_arguments(update):
    args = (update.effective_message.text or "").split()
    if len(args) != COMMAND_WITH_NOTE or not all(item.isdigit() for item in args[1:]):
        await update.effective_message.reply_text("格式：/assign 订单编号 新发放人员ID（0 表示管理员接管）")
        return
    return args
