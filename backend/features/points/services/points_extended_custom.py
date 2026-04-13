from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import (
    CustomPointAccount,
    CustomPointLedger,
    CustomPointType,
    TgChat,
)
from backend.shared.services.base import ValidationError


class PointsExtendedCustomMixin:
    @staticmethod
    async def _lock_chat_scope(session: AsyncSession, chat_id: int) -> None:
        await session.execute(select(TgChat.id).where(TgChat.id == chat_id).with_for_update())

    @staticmethod
    async def _ensure_custom_point_name_unique(
        session: AsyncSession,
        *,
        chat_id: int,
        name: str,
        exclude_type_id: int | None = None,
    ) -> None:
        stmt = select(CustomPointType.id).where(CustomPointType.chat_id == chat_id, CustomPointType.name == name)
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
            select(CustomPointType).where(CustomPointType.chat_id == chat_id, CustomPointType.id == type_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_custom_point_type(
        session: AsyncSession,
        chat_id: int,
        created_by_user_id: int,
    ) -> CustomPointType:
        await PointsExtendedCustomMixin._lock_chat_scope(session, chat_id)
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
            await PointsExtendedCustomMixin._ensure_custom_point_name_unique(
                session,
                chat_id=item.chat_id,
                name=normalized_name,
                exclude_type_id=item.id,
            )
            item.name = normalized_name
        if rank_command is not None:
            normalized_command = rank_command.strip() if rank_command else None
            if normalized_command:
                await PointsExtendedCustomMixin._ensure_custom_point_rank_command_unique(
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
        await PointsExtendedCustomMixin._lock_chat_scope(session, chat_id)
        result = await session.execute(
            select(CustomPointAccount)
            .where(
                CustomPointAccount.chat_id == chat_id,
                CustomPointAccount.type_id == type_id,
                CustomPointAccount.user_id == user_id,
            )
            .with_for_update()
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
            select(CustomPointAccount).where(CustomPointAccount.chat_id == chat_id, CustomPointAccount.type_id == type_id)
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
            .where(CustomPointLedger.chat_id == chat_id, CustomPointLedger.type_id == type_id)
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
            .where(CustomPointAccount.chat_id == chat_id, CustomPointAccount.type_id == type_id)
            .order_by(CustomPointAccount.balance.desc(), CustomPointAccount.user_id.asc())
            .limit(limit)
        )
        return [(int(user_id), int(balance)) for user_id, balance in result.all()]
