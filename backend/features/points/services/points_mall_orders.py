from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.core import PointsMallOrder, PointsMallOrderLog, PointsMallProduct
from backend.platform.db.schema.models.enums import PointsTxnType


class PointsMallOrdersMixin:
    @staticmethod
    async def count_user_product_orders(
        session: AsyncSession,
        *,
        chat_id: int,
        product_id: int,
        user_id: int,
    ) -> int:
        result = await session.execute(
            select(func.count(PointsMallOrder.order_id)).where(
                PointsMallOrder.chat_id == chat_id,
                PointsMallOrder.product_id == product_id,
                PointsMallOrder.buyer_user_id == user_id,
                PointsMallOrder.order_status.in_(["created", "fulfilled"]),
            )
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    async def count_orders(session: AsyncSession, chat_id: int) -> int:
        result = await session.execute(select(func.count(PointsMallOrder.order_id)).where(PointsMallOrder.chat_id == chat_id))
        return int(result.scalar_one() or 0)

    @staticmethod
    async def list_recent_orders(
        session: AsyncSession,
        chat_id: int,
        limit: int = 20,
        *,
        product_id: int | None = None,
        order_status: str | None = None,
    ) -> list[PointsMallOrder]:
        stmt = select(PointsMallOrder).where(PointsMallOrder.chat_id == chat_id)
        if product_id is not None:
            stmt = stmt.where(PointsMallOrder.product_id == product_id)
        if order_status and order_status != "all":
            stmt = stmt.where(PointsMallOrder.order_status == order_status)
        result = await session.execute(
            stmt.order_by(PointsMallOrder.created_at.desc(), PointsMallOrder.order_id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_orders_by_status(
        session: AsyncSession,
        *,
        chat_id: int,
        product_id: int | None = None,
    ) -> dict[str, int]:
        stmt = (
            select(PointsMallOrder.order_status, func.count(PointsMallOrder.order_id))
            .where(PointsMallOrder.chat_id == chat_id)
            .group_by(PointsMallOrder.order_status)
        )
        if product_id is not None:
            stmt = stmt.where(PointsMallOrder.product_id == product_id)
        result = await session.execute(stmt)
        stats: dict[str, int] = {"all": 0, "created": 0, "fulfilled": 0, "canceled": 0, "refunded": 0}
        for status, count in result.all():
            normalized = str(status or "")
            stats[normalized] = int(count or 0)
        stats["all"] = sum(count for key, count in stats.items() if key != "all")
        return stats

    @staticmethod
    async def list_order_logs(
        session: AsyncSession,
        *,
        order_id: int,
        limit: int = 10,
    ) -> list[PointsMallOrderLog]:
        result = await session.execute(
            select(PointsMallOrderLog)
            .where(PointsMallOrderLog.order_id == order_id)
            .order_by(PointsMallOrderLog.created_at.desc(), PointsMallOrderLog.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_order(session: AsyncSession, chat_id: int, order_id: int) -> PointsMallOrder | None:
        result = await session.execute(
            select(PointsMallOrder).where(PointsMallOrder.chat_id == chat_id, PointsMallOrder.order_id == order_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def fulfill_order(
        session: AsyncSession,
        *,
        chat_id: int,
        order_id: int,
        operator_user_id: int,
    ) -> tuple[bool, str, PointsMallOrder | None]:
        result = await session.execute(
            select(PointsMallOrder)
            .where(PointsMallOrder.chat_id == chat_id, PointsMallOrder.order_id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False, "订单不存在", None
        if order.order_status != "created":
            return False, "仅待处理订单可标记发放", order
        order.order_status = "fulfilled"
        order.operator_user_id = operator_user_id
        order.updated_at = dt.datetime.now(dt.UTC)
        session.add(PointsMallOrderLog(order_id=order.order_id, action="fulfill", payload={"operator_user_id": operator_user_id}))
        await session.flush()
        return True, "订单已标记为已发放", order

    @staticmethod
    async def cancel_order(
        session: AsyncSession,
        *,
        chat_id: int,
        order_id: int,
        operator_user_id: int,
    ) -> tuple[bool, str, PointsMallOrder | None]:
        result = await session.execute(
            select(PointsMallOrder)
            .where(PointsMallOrder.chat_id == chat_id, PointsMallOrder.order_id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False, "订单不存在", None
        if order.order_status != "created":
            return False, "仅待处理订单可取消", order

        product_result = await session.execute(
            select(PointsMallProduct)
            .where(PointsMallProduct.chat_id == chat_id, PointsMallProduct.product_id == order.product_id)
            .with_for_update()
        )
        product = product_result.scalar_one_or_none()
        if product is not None:
            product.stock_left = min(int(product.stock_left) + int(order.quantity), int(product.stock_total))
            if product.stock_left > 0 and product.status == "off_sale":
                product.status = "on_sale"
            product.updated_at = dt.datetime.now(dt.UTC)

        await change_points(
            session,
            chat_id=chat_id,
            user_id=order.buyer_user_id,
            amount=int(order.price_points),
            txn_type=PointsTxnType.bonus.value,
            reason=f"订单取消退款:{order.order_id}",
        )
        order.order_status = "canceled"
        order.operator_user_id = operator_user_id
        order.updated_at = dt.datetime.now(dt.UTC)
        session.add(PointsMallOrderLog(order_id=order.order_id, action="cancel", payload={"operator_user_id": operator_user_id}))
        await session.flush()
        return True, "订单已取消并退款", order

    @staticmethod
    async def refund_order(
        session: AsyncSession,
        *,
        chat_id: int,
        order_id: int,
        operator_user_id: int,
    ) -> tuple[bool, str, PointsMallOrder | None]:
        result = await session.execute(
            select(PointsMallOrder)
            .where(PointsMallOrder.chat_id == chat_id, PointsMallOrder.order_id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False, "订单不存在", None
        if order.order_status == "refunded":
            return False, "订单已退款", order
        if order.order_status == "canceled":
            return False, "已取消订单无需重复退款", order
        if order.order_status not in {"created", "fulfilled"}:
            return False, "当前订单状态不支持退款", order

        if order.order_status == "created":
            product_result = await session.execute(
                select(PointsMallProduct)
                .where(PointsMallProduct.chat_id == chat_id, PointsMallProduct.product_id == order.product_id)
                .with_for_update()
            )
            product = product_result.scalar_one_or_none()
            if product is not None:
                product.stock_left = min(int(product.stock_left) + int(order.quantity), int(product.stock_total))
                if product.stock_left > 0 and product.status == "off_sale":
                    product.status = "on_sale"
                product.updated_at = dt.datetime.now(dt.UTC)

        await change_points(
            session,
            chat_id=chat_id,
            user_id=order.buyer_user_id,
            amount=int(order.price_points),
            txn_type=PointsTxnType.bonus.value,
            reason=f"订单退款:{order.order_id}",
        )
        order.order_status = "refunded"
        order.operator_user_id = operator_user_id
        order.updated_at = dt.datetime.now(dt.UTC)
        session.add(PointsMallOrderLog(order_id=order.order_id, action="refund", payload={"operator_user_id": operator_user_id}))
        await session.flush()
        return True, "订单已退款", order
