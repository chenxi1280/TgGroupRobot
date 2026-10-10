from __future__ import annotations

from backend.features.admin.support import *


_ORDER_STATUSES = {"all", "created", "fulfilled", "canceled", "refunded"}
_ORDER_STATUS_NAMES = {
    "all": "全部",
    "created": "待发放",
    "fulfilled": "已人工标记发放",
    "canceled": "已取消",
    "refunded": "已退款",
}


def _normalize_order_status(status: str) -> str:
    return status if status in _ORDER_STATUSES else "all"


def _format_orders_page(orders: list, *, product_id: int | None, status: str, summary: str, page: int = 0, total: int | None = None) -> str:
    title = "🧾 管理订单" if product_id is None else f"🧾 管理订单 | 商品 {product_id}"
    lines = [title, f"当前筛选：{_ORDER_STATUS_NAMES.get(status, '全部')}", summary, ""]
    for order in orders:
        lines.extend([
            f"订单#{order.order_id}｜商品 {order.product_id}", f"用户：{order.buyer_user_id}",
            f"积分：{order.price_points}｜数量：{order.quantity}", f"状态：{_ORDER_STATUS_NAMES.get(order.order_status, order.order_status)}", "",
        ])
    total = len(orders) if total is None else total
    lines.append(f"{total} 条数据，第 {page + 1} 页/共 {max(1, (total + 7) // 8)} 页")
    return "\n".join(lines)


class PointsMallOrderPagesMixin:
    async def _show_points_mall_orders_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, product_id: int | None = None,
        status: str = "all",
        page: int = 0,
    ) -> None:
        """显示积分商城订单管理页"""
        normalized_status = _normalize_order_status(status)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            status_counts = await PointsExtendedService.count_orders_by_status(
                session, chat_id=chat_id, product_id=product_id,
            )
            total = status_counts.get(normalized_status, 0)
            page = max(0, min(page, max(0, (total - 1) // 8)))
            orders = await PointsExtendedService.list_recent_orders(
                session, chat_id, limit=8, offset=page * 8,
                product_id=product_id, order_status=normalized_status,
            )
            await session.commit()
        summary = _format_order_status_summary(status_counts)
        text = _format_orders_page(
            orders, product_id=product_id, status=normalized_status, summary=summary, page=page, total=total,
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_orders_keyboard(
                chat_id,
                orders=orders,
                product_id=product_id,
                status=normalized_status,
                status_counts=status_counts, page=page, total=total,
            ),
        )

    async def _show_points_mall_order_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, order_id: int,

        status: str = "all",
        product_id: int | None = None,
        page: int = 0,
    ) -> None:
        normalized_status = _normalize_order_status(status)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            order = await PointsExtendedService.get_order(session, chat_id, order_id)
            logs = await PointsExtendedService.list_order_logs(session, order_id=order_id, limit=5)
            await session.commit()
        if order is None:
            await answer_callback_query_safely(update, "订单不存在", show_alert=True)
            await self._show_points_mall_orders_page(update, context, chat_id, product_id=product_id, status=normalized_status, page=page)
            return
        log_lines = _format_order_logs(logs)
        text = "\n".join(
            [
                "🧾 管理订单 | 订单详情",
                "",
                f"订单编号：{order.order_id}",
                f"商品编号：{order.product_id}",
                f"购买用户：{order.buyer_user_id}",
                f"所需积分：{order.price_points}",
                f"数量：{order.quantity}",
                f"订单状态：{_ORDER_STATUS_NAMES.get(order.order_status, order.order_status)}",
                f"操作人员：{order.operator_user_id or '未处理'}",
                "",
                *log_lines,
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_order_detail_keyboard(
                chat_id,
                order,
                status=normalized_status,
                product_id=product_id, page=page,
            ),
        )


def _format_order_status_summary(status_counts: dict[str, int]) -> str:
    return (
        f"📊 全部 {status_counts.get('all', 0)}"
        f"｜🟡 待处理 {status_counts.get('created', 0)}"
        f"｜✅ 已发放 {status_counts.get('fulfilled', 0)}"
        f"｜❌ 已取消 {status_counts.get('canceled', 0)}"
        f"｜💸 已退款 {status_counts.get('refunded', 0)}"
    )


def _format_order_logs(logs) -> list[str]:
    log_lines = ["最近操作："]
    if not logs:
        log_lines.append("- 暂无日志")
        return log_lines
    for item in logs:
        payload = item.payload or {}
        operator = payload.get("operator_user_id", "-")
        timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
        log_lines.append(f"- {timestamp}｜{item.action}｜操作人 {operator}")
    return log_lines
