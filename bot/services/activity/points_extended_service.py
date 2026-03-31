from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import (
    ChatMember,
    CustomPointAccount,
    CustomPointLedger,
    CustomPointType,
    PointsAccount,
    PointsLevel,
    PointsLevelSetting,
    PointsMallOrder,
    PointsMallOrderLog,
    PointsMallProduct,
    PointsMallSetting,
    TgChat,
    TgUser,
)
from bot.models.enums import PointsTxnType
from bot.models.garage_features import GarageCertifiedTeacher, TeacherProfile
from bot.services.activity.points_service import change_points, get_balance
from bot.services.base import ValidationError
from bot.services.core.user_service import ensure_user


_UNSET = object()


class PointsExtendedService:
    @staticmethod
    async def _lock_chat_scope(session: AsyncSession, chat_id: int) -> None:
        await session.execute(
            select(TgChat.id).where(TgChat.id == chat_id).with_for_update()
        )

    @staticmethod
    async def _ensure_custom_point_name_unique(
        session: AsyncSession,
        *,
        chat_id: int,
        name: str,
        exclude_type_id: int | None = None,
    ) -> None:
        stmt = select(CustomPointType.id).where(
            CustomPointType.chat_id == chat_id,
            CustomPointType.name == name,
        )
        if exclude_type_id is not None:
            stmt = stmt.where(CustomPointType.id != exclude_type_id)
        result = await session.execute(stmt.limit(1))
        if result.scalar_one_or_none() is not None:
            raise ValidationError("该积分名字已存在，请更换一个名字。")

    @staticmethod
    async def _ensure_custom_point_rank_command_unique(
        session: AsyncSession,
        *,
        chat_id: int,
        rank_command: str,
        exclude_type_id: int | None = None,
    ) -> None:
        stmt = select(CustomPointType.id).where(
            CustomPointType.chat_id == chat_id,
            CustomPointType.rank_command == rank_command,
        )
        if exclude_type_id is not None:
            stmt = stmt.where(CustomPointType.id != exclude_type_id)
        result = await session.execute(stmt.limit(1))
        if result.scalar_one_or_none() is not None:
            raise ValidationError("该排行指令已存在，请更换一个指令。")

    @staticmethod
    async def _ensure_level_threshold_unique(
        session: AsyncSession,
        *,
        chat_id: int,
        point_threshold: int,
        exclude_level_id: int | None = None,
    ) -> None:
        stmt = select(PointsLevel.id).where(
            PointsLevel.chat_id == chat_id,
            PointsLevel.point_threshold == point_threshold,
        )
        if exclude_level_id is not None:
            stmt = stmt.where(PointsLevel.id != exclude_level_id)
        result = await session.execute(stmt.limit(1))
        if result.scalar_one_or_none() is not None:
            raise ValidationError("该积分门槛已存在，请重新设置。")

    @staticmethod
    async def list_custom_point_types(session: AsyncSession, chat_id: int) -> list[CustomPointType]:
        result = await session.execute(
            select(CustomPointType)
            .where(CustomPointType.chat_id == chat_id)
            .order_by(CustomPointType.type_no.asc(), CustomPointType.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_custom_point_type(session: AsyncSession, chat_id: int, type_id: int) -> CustomPointType | None:
        result = await session.execute(
            select(CustomPointType).where(
                CustomPointType.chat_id == chat_id,
                CustomPointType.id == type_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_custom_point_type(
        session: AsyncSession,
        chat_id: int,
        created_by_user_id: int,
    ) -> CustomPointType:
        await PointsExtendedService._lock_chat_scope(session, chat_id)
        next_no_result = await session.execute(
            select(func.coalesce(func.max(CustomPointType.type_no), 0) + 1).where(CustomPointType.chat_id == chat_id)
        )
        next_no = int(next_no_result.scalar_one())
        item = CustomPointType(
            chat_id=chat_id,
            type_no=next_no,
            name=f"待配置{next_no}",
            rank_command=None,
            enabled=True,
            created_by_user_id=created_by_user_id,
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def update_custom_point_type(
        session: AsyncSession,
        item: CustomPointType,
        *,
        enabled: bool | None = None,
        name: str | None = None,
        rank_command: str | None = None,
    ) -> CustomPointType:
        if enabled is not None:
            item.enabled = enabled
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValidationError("积分名字不能为空。")
            await PointsExtendedService._ensure_custom_point_name_unique(
                session,
                chat_id=item.chat_id,
                name=normalized_name,
                exclude_type_id=item.id,
            )
            item.name = normalized_name
        if rank_command is not None:
            normalized_command = rank_command.strip() if rank_command else None
            if normalized_command:
                await PointsExtendedService._ensure_custom_point_rank_command_unique(
                    session,
                    chat_id=item.chat_id,
                    rank_command=normalized_command,
                    exclude_type_id=item.id,
                )
            item.rank_command = normalized_command
        item.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return item

    @staticmethod
    async def delete_custom_point_type(session: AsyncSession, item: CustomPointType) -> None:
        await session.delete(item)
        await session.flush()

    @staticmethod
    async def adjust_custom_points(
        session: AsyncSession,
        *,
        chat_id: int,
        type_id: int,
        user_id: int,
        delta: int,
        operator_user_id: int | None,
        reason_note: str | None = None,
    ) -> int:
        await PointsExtendedService._lock_chat_scope(session, chat_id)
        result = await session.execute(
            select(CustomPointAccount).where(
                CustomPointAccount.chat_id == chat_id,
                CustomPointAccount.type_id == type_id,
                CustomPointAccount.user_id == user_id,
            ).with_for_update()
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = CustomPointAccount(chat_id=chat_id, type_id=type_id, user_id=user_id, balance=0)
            session.add(account)
            await session.flush()
        account.balance += delta
        account.updated_at = dt.datetime.now(dt.UTC)
        session.add(
            CustomPointLedger(
                chat_id=chat_id,
                type_id=type_id,
                user_id=user_id,
                delta=delta,
                reason_note=reason_note,
                operator_user_id=operator_user_id,
            )
        )
        await session.flush()
        return int(account.balance)

    @staticmethod
    async def clear_custom_points(
        session: AsyncSession,
        *,
        chat_id: int,
        type_id: int,
        operator_user_id: int | None = None,
        reason_note: str | None = None,
    ) -> int:
        result = await session.execute(
            select(CustomPointAccount).where(
                CustomPointAccount.chat_id == chat_id,
                CustomPointAccount.type_id == type_id,
            )
        )
        accounts = list(result.scalars().all())
        cleared = 0
        for account in accounts:
            if account.balance != 0:
                previous_balance = int(account.balance)
                account.balance = 0
                account.updated_at = dt.datetime.now(dt.UTC)
                session.add(
                    CustomPointLedger(
                        chat_id=chat_id,
                        type_id=type_id,
                        user_id=account.user_id,
                        delta=-previous_balance,
                        reason_note=reason_note or "清空自定义积分",
                        operator_user_id=operator_user_id,
                    )
                )
                cleared += 1
        await session.flush()
        return cleared

    @staticmethod
    async def list_custom_point_ledger(
        session: AsyncSession,
        *,
        chat_id: int,
        type_id: int,
        limit: int = 50,
    ) -> list[CustomPointLedger]:
        result = await session.execute(
            select(CustomPointLedger)
            .where(
                CustomPointLedger.chat_id == chat_id,
                CustomPointLedger.type_id == type_id,
            )
            .order_by(CustomPointLedger.created_at.desc(), CustomPointLedger.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_custom_point_leaderboard(
        session: AsyncSession,
        *,
        chat_id: int,
        type_id: int,
        limit: int = 10,
    ) -> list[tuple[int, int]]:
        result = await session.execute(
            select(CustomPointAccount.user_id, CustomPointAccount.balance)
            .where(
                CustomPointAccount.chat_id == chat_id,
                CustomPointAccount.type_id == type_id,
            )
            .order_by(CustomPointAccount.balance.desc(), CustomPointAccount.user_id.asc())
            .limit(limit)
        )
        return [(int(user_id), int(balance)) for user_id, balance in result.all()]

    @staticmethod
    async def get_or_create_level_setting(session: AsyncSession, chat_id: int) -> PointsLevelSetting:
        result = await session.execute(select(PointsLevelSetting).where(PointsLevelSetting.chat_id == chat_id))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = PointsLevelSetting(chat_id=chat_id, enabled=False, exclude_teacher_enabled=False)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def list_levels(session: AsyncSession, chat_id: int) -> list[PointsLevel]:
        result = await session.execute(
            select(PointsLevel)
            .where(PointsLevel.chat_id == chat_id)
            .order_by(PointsLevel.point_threshold.asc(), PointsLevel.level_no.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_level(session: AsyncSession, chat_id: int, level_id: int) -> PointsLevel | None:
        result = await session.execute(
            select(PointsLevel).where(PointsLevel.chat_id == chat_id, PointsLevel.id == level_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_level(session: AsyncSession, chat_id: int) -> PointsLevel:
        await PointsExtendedService._lock_chat_scope(session, chat_id)
        next_no_result = await session.execute(
            select(func.coalesce(func.max(PointsLevel.level_no), 0) + 1).where(PointsLevel.chat_id == chat_id)
        )
        next_no = int(next_no_result.scalar_one())
        max_threshold_result = await session.execute(
            select(func.coalesce(func.max(PointsLevel.point_threshold), 0)).where(PointsLevel.chat_id == chat_id)
        )
        next_threshold = int(max_threshold_result.scalar_one()) + 1
        level = PointsLevel(
            chat_id=chat_id,
            level_no=next_no,
            level_name=f"待配置{next_no}",
            point_threshold=next_threshold,
            enabled=True,
        )
        session.add(level)
        await session.flush()
        return level

    @staticmethod
    async def update_level_setting(
        session: AsyncSession,
        setting: PointsLevelSetting,
        *,
        enabled: bool | None = None,
        exclude_teacher_enabled: bool | None = None,
    ) -> PointsLevelSetting:
        if enabled is not None:
            setting.enabled = enabled
        if exclude_teacher_enabled is not None:
            setting.exclude_teacher_enabled = exclude_teacher_enabled
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

    @staticmethod
    async def update_level(
        session: AsyncSession,
        level: PointsLevel,
        *,
        level_name: str | None = None,
        point_threshold: int | None = None,
        perm_name: str | None = None,
        perm_value: bool | None = None,
    ) -> PointsLevel:
        if level_name is not None:
            normalized_name = level_name.strip()
            if not normalized_name:
                raise ValidationError("等级名称不能为空。")
            level.level_name = normalized_name
        if point_threshold is not None:
            if int(point_threshold) <= 0:
                raise ValidationError("积分门槛必须大于 0。")
            await PointsExtendedService._ensure_level_threshold_unique(
                session,
                chat_id=level.chat_id,
                point_threshold=int(point_threshold),
                exclude_level_id=level.id,
            )
            level.point_threshold = point_threshold
        if perm_name is not None and perm_value is not None and hasattr(level, perm_name):
            setattr(level, perm_name, perm_value)
        level.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return level

    @staticmethod
    async def delete_level(session: AsyncSession, level: PointsLevel) -> None:
        await session.delete(level)
        await session.flush()

    @staticmethod
    async def resolve_user_level(session: AsyncSession, chat_id: int, user_id: int) -> PointsLevel | None:
        setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
        if not setting.enabled:
            return None
        balance = await get_balance(session, chat_id, user_id)
        result = await session.execute(
            select(PointsLevel)
            .where(
                PointsLevel.chat_id == chat_id,
                PointsLevel.enabled.is_(True),
                PointsLevel.point_threshold <= balance,
            )
            .order_by(PointsLevel.point_threshold.desc(), PointsLevel.level_no.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def is_teacher_exempt(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        certified_result = await session.execute(
            select(GarageCertifiedTeacher.id).where(
                GarageCertifiedTeacher.chat_id == chat_id,
                GarageCertifiedTeacher.user_id == user_id,
                GarageCertifiedTeacher.enabled.is_(True),
            )
        )
        if certified_result.scalar_one_or_none() is not None:
            return True

        profile_result = await session.execute(
            select(TeacherProfile.id).where(
                TeacherProfile.chat_id == chat_id,
                TeacherProfile.user_id == user_id,
            )
        )
        return profile_result.scalar_one_or_none() is not None

    @staticmethod
    async def get_or_create_mall_setting(session: AsyncSession, chat_id: int) -> PointsMallSetting:
        result = await session.execute(select(PointsMallSetting).where(PointsMallSetting.chat_id == chat_id))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = PointsMallSetting(chat_id=chat_id)
            session.add(setting)
            await session.flush()
        return setting

    @staticmethod
    async def update_mall_setting(
        session: AsyncSession,
        setting: PointsMallSetting,
        *,
        enabled: bool | None = None,
        auto_unlist_when_out_of_stock: bool | None = None,
        entry_command: str | None = None,
        redeem_notice_delete_seconds: int | None = None,
        cover_media_type: str | None | Any = _UNSET,
        cover_file_id: str | None | Any = _UNSET,
    ) -> PointsMallSetting:
        if enabled is not None:
            setting.enabled = enabled
        if auto_unlist_when_out_of_stock is not None:
            setting.auto_unlist_when_out_of_stock = auto_unlist_when_out_of_stock
        if entry_command is not None:
            setting.entry_command = entry_command
        if redeem_notice_delete_seconds is not None:
            setting.redeem_notice_delete_seconds = max(int(redeem_notice_delete_seconds), 0)
        if cover_media_type is not _UNSET or cover_file_id is not _UNSET:
            setting.cover_media_type = cover_media_type
            setting.cover_file_id = cover_file_id
        setting.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
        return setting

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
        name: str | None | Any = _UNSET,
        price_points: int | None | Any = _UNSET,
        limit_per_user: int | None | Any = _UNSET,
        stock_total: int | None | Any = _UNSET,
        stock_left: int | None | Any = _UNSET,
        fulfiller_user_id: int | None | Any = _UNSET,
        description: str | None | Any = _UNSET,
        sort_weight: int | None | Any = _UNSET,
        cover_media_type: str | None | Any = _UNSET,
        cover_file_id: str | None | Any = _UNSET,
    ) -> PointsMallProduct:
        if name is not _UNSET:
            product.name = name
        if price_points is not _UNSET:
            product.price_points = price_points
        if limit_per_user is not _UNSET:
            product.limit_per_user = limit_per_user
        if stock_total is not _UNSET:
            product.stock_total = stock_total
        if stock_left is not _UNSET:
            product.stock_left = stock_left
        if fulfiller_user_id is not _UNSET:
            product.fulfiller_user_id = fulfiller_user_id
        if description is not _UNSET:
            product.description = description
        if sort_weight is not _UNSET:
            product.sort_weight = sort_weight
        if cover_media_type is not _UNSET or cover_file_id is not _UNSET:
            product.cover_media_type = cover_media_type
            product.cover_file_id = cover_file_id
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
    async def redeem_product(
        session: AsyncSession,
        *,
        chat_id: int,
        product_id: int,
        buyer_user_id: int,
    ) -> tuple[bool, str, PointsMallOrder | None]:
        result = await session.execute(
            select(PointsMallProduct)
            .where(
                PointsMallProduct.chat_id == chat_id,
                PointsMallProduct.product_id == product_id,
            )
            .with_for_update()
        )
        product = result.scalar_one_or_none()
        if product is None:
            return False, "商品不存在", None
        if product.status != "on_sale":
            return False, "商品未上架", None
        if product.stock_left <= 0:
            return False, "商品库存不足", None

        account_result = await session.execute(
            select(PointsAccount)
            .where(
                PointsAccount.chat_id == chat_id,
                PointsAccount.user_id == buyer_user_id,
            )
            .with_for_update()
        )
        account = account_result.scalar_one_or_none()
        if account is None:
            account = PointsAccount(chat_id=chat_id, user_id=buyer_user_id, balance=0)
            session.add(account)
            await session.flush()

        if product.limit_per_user:
            used = await PointsExtendedService.count_user_product_orders(
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
        if product.stock_left <= 0 and (
            await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
        ).auto_unlist_when_out_of_stock:
            product.status = "off_sale"
        product.updated_at = dt.datetime.now(dt.UTC)

        order = PointsMallOrder(
            chat_id=chat_id,
            product_id=product.product_id,
            buyer_user_id=buyer_user_id,
            price_points=product.price_points,
            quantity=1,
            order_status="created",
            operator_user_id=None,
        )
        session.add(order)
        await session.flush()
        session.add(
            PointsMallOrderLog(
                order_id=order.order_id,
                action="redeem",
                payload={
                    "product_id": product.product_id,
                    "buyer_user_id": buyer_user_id,
                    "price_points": product.price_points,
                },
            )
        )
        await session.flush()
        return True, "兑换成功", order

    @staticmethod
    async def delete_product(session: AsyncSession, product: PointsMallProduct) -> None:
        await session.delete(product)
        await session.flush()

    @staticmethod
    async def count_orders(session: AsyncSession, chat_id: int) -> int:
        result = await session.execute(
            select(func.count(PointsMallOrder.order_id)).where(PointsMallOrder.chat_id == chat_id)
        )
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
            stmt
            .order_by(PointsMallOrder.created_at.desc(), PointsMallOrder.order_id.desc())
            .limit(limit)
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
            if normalized in stats:
                stats[normalized] = int(count or 0)
            else:
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
            select(PointsMallOrder).where(
                PointsMallOrder.chat_id == chat_id,
                PointsMallOrder.order_id == order_id,
            )
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
            select(PointsMallOrder).where(
                PointsMallOrder.chat_id == chat_id,
                PointsMallOrder.order_id == order_id,
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False, "订单不存在", None
        if order.order_status != "created":
            return False, "仅待处理订单可标记发放", order

        order.order_status = "fulfilled"
        order.operator_user_id = operator_user_id
        order.updated_at = dt.datetime.now(dt.UTC)
        session.add(
            PointsMallOrderLog(
                order_id=order.order_id,
                action="fulfill",
                payload={"operator_user_id": operator_user_id},
            )
        )
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
            select(PointsMallOrder).where(
                PointsMallOrder.chat_id == chat_id,
                PointsMallOrder.order_id == order_id,
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False, "订单不存在", None
        if order.order_status != "created":
            return False, "仅待处理订单可取消", order

        product_result = await session.execute(
            select(PointsMallProduct).where(
                PointsMallProduct.chat_id == chat_id,
                PointsMallProduct.product_id == order.product_id,
            ).with_for_update()
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
        session.add(
            PointsMallOrderLog(
                order_id=order.order_id,
                action="cancel",
                payload={"operator_user_id": operator_user_id},
            )
        )
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
            select(PointsMallOrder).where(
                PointsMallOrder.chat_id == chat_id,
                PointsMallOrder.order_id == order_id,
            ).with_for_update()
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
                select(PointsMallProduct).where(
                    PointsMallProduct.chat_id == chat_id,
                    PointsMallProduct.product_id == order.product_id,
                ).with_for_update()
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
        session.add(
            PointsMallOrderLog(
                order_id=order.order_id,
                action="refund",
                payload={"operator_user_id": operator_user_id},
            )
        )
        await session.flush()
        return True, "订单已退款", order

    @staticmethod
    async def is_chat_member(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(ChatMember.id).where(
                ChatMember.chat_id == chat_id,
                ChatMember.user_id == user_id,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def resolve_user_id(session: AsyncSession, raw_value: str) -> int | None:
        value = raw_value.strip()
        if not value:
            return None
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            user_id = int(value)
            await ensure_user(session, user_id=user_id, username=None, first_name=None, last_name=None, language_code=None)
            return user_id
        username = value.lstrip("@").lower()
        result = await session.execute(
            select(TgUser.id).where(func.lower(TgUser.username) == username)
        )
        return result.scalar_one_or_none()
