from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_mall_settings import UNSET
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.core import PointsAccount, PointsMallOrder, PointsMallOrderLog, PointsMallProduct
from backend.platform.db.schema.models.enums import PointsTxnType


async def _lock_redeemable_product(session, chat_id: int, product_id: int):
    result = await session.execute(
        select(PointsMallProduct)
        .where(PointsMallProduct.chat_id == chat_id, PointsMallProduct.product_id == product_id)
        .with_for_update()
    )
    product = result.scalar_one_or_none()
    if product is None:
        return None, "商品不存在"
    if product.status != "on_sale":
        return None, "商品未上架"
    if product.stock_left <= 0:
        return None, "商品库存不足"
    return product, None


async def _ensure_points_account(session, chat_id: int, user_id: int) -> PointsAccount:
    result = await session.execute(
        select(PointsAccount)
        .where(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id)
        .with_for_update()
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(account)
        await session.flush()
    return account


async def _create_redeem_order(session, product, *, chat_id: int, buyer_user_id: int) -> PointsMallOrder:
    order = PointsMallOrder(
        chat_id=chat_id, product_id=product.product_id, buyer_user_id=buyer_user_id,
        price_points=product.price_points, quantity=1, order_status="created", operator_user_id=None,
    )
    session.add(order)
    await session.flush()
    session.add(PointsMallOrderLog(
        order_id=order.order_id, action="redeem",
        payload={"product_id": product.product_id, "buyer_user_id": buyer_user_id, "price_points": product.price_points},
    ))
    await session.flush()
    return order


class PointsMallProductsMixin:
    @staticmethod
    async def list_products(session: AsyncSession, chat_id: int) -> list[PointsMallProduct]:
        result = await session.execute(
            select(PointsMallProduct)
            .where(PointsMallProduct.chat_id == chat_id)
            .order_by(PointsMallProduct.sort_weight.desc(), PointsMallProduct.product_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_product(session: AsyncSession, chat_id: int, product_id: int) -> PointsMallProduct | None:
        result = await session.execute(
            select(PointsMallProduct).where(
                PointsMallProduct.chat_id == chat_id,
                PointsMallProduct.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_product(session: AsyncSession, chat_id: int) -> PointsMallProduct:
        product = PointsMallProduct(
            chat_id=chat_id,
            name="待配置商品",
            price_points=1,
            stock_total=0,
            stock_left=0,
            status="off_sale",
            sort_weight=0,
        )
        session.add(product)
        await session.flush()
        return product

    @staticmethod
    async def update_product_status(
        session: AsyncSession,
        product: PointsMallProduct,
        *,
        on_sale: bool,
    ) -> PointsMallProduct:
        product.status = "on_sale" if on_sale else "off_sale"
        product.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return product

    @staticmethod
    async def update_product(
        session: AsyncSession,
        product: PointsMallProduct,
        *,
        name: str | None | Any = UNSET,
        price_points: int | None | Any = UNSET,
        limit_per_user: int | None | Any = UNSET,
        stock_total: int | None | Any = UNSET,
        stock_left: int | None | Any = UNSET,
        fulfiller_user_id: int | None | Any = UNSET,
        description: str | None | Any = UNSET,
        sort_weight: int | None | Any = UNSET,
        cover_media_type: str | None | Any = UNSET,
        cover_file_id: str | None | Any = UNSET,
    ) -> PointsMallProduct:
        updates = {
            "name": name, "price_points": price_points, "limit_per_user": limit_per_user,
            "stock_total": stock_total, "stock_left": stock_left,
            "fulfiller_user_id": fulfiller_user_id, "description": description,
            "sort_weight": sort_weight, "cover_media_type": cover_media_type,
            "cover_file_id": cover_file_id,
        }
        for field, value in updates.items():
            if value is not UNSET:
                setattr(product, field, value)
        product.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return product

    @staticmethod
    async def update_product_stock_total(
        session: AsyncSession,
        product: PointsMallProduct,
        *,
        stock_total: int,
    ) -> PointsMallProduct:
        consumed = max(int(product.stock_total) - int(product.stock_left), 0)
        next_left = max(int(stock_total) - consumed, 0)
        product.stock_total = int(stock_total)
        product.stock_left = next_left
        product.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return product

    @staticmethod
    async def list_on_sale_products(session: AsyncSession, chat_id: int) -> list[PointsMallProduct]:
        result = await session.execute(
            select(PointsMallProduct)
            .where(
                PointsMallProduct.chat_id == chat_id,
                PointsMallProduct.status == "on_sale",
            )
            .order_by(PointsMallProduct.sort_weight.desc(), PointsMallProduct.product_id.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def redeem_product(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        product_id: int,
        buyer_user_id: int,
    ) -> tuple[bool, str, PointsMallOrder | None]:
        product, error = await _lock_redeemable_product(session, chat_id, product_id)
        if product is None:
            return False, error, None
        await _ensure_points_account(session, chat_id, buyer_user_id)

        if product.limit_per_user:
            used = await cls.count_user_product_orders(
                session,
                chat_id=chat_id,
                product_id=product_id,
                user_id=buyer_user_id,
            )
            if used >= product.limit_per_user:
                return False, "已达到限购次数", None

        success, _balance = await change_points(
            session,
            chat_id=chat_id,
            user_id=buyer_user_id,
            amount=-int(product.price_points),
            txn_type=PointsTxnType.penalty.value,
            reason=f"兑换商品:{product.name}",
        )
        if not success:
            return False, "积分不足", None

        product.stock_left -= 1
        if product.stock_left <= 0 and (await cls.get_or_create_mall_setting(session, chat_id)).auto_unlist_when_out_of_stock:
            product.status = "off_sale"
        product.updated_at = dt.datetime.now(dt.UTC)

        order = await _create_redeem_order(
            session, product, chat_id=chat_id, buyer_user_id=buyer_user_id,
        )
        return True, "兑换成功", order

    @staticmethod
    async def delete_product(session: AsyncSession, product: PointsMallProduct) -> None:
        await session.delete(product)
        await session.flush()
