from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.alliance import GroupAlliance, GroupAllianceBanPool, GroupAllianceSetting, GroupAllianceMember
from backend.shared.services.base import NotFoundError, ValidationError


class AllianceBanMixin:
    @classmethod
    async def set_joint_ban_enabled(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
        enabled: bool,
    ) -> GroupAllianceSetting:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise NotFoundError("当前群尚未加入联盟。")
        setting = await cls.ensure_setting(session, chat_id, member.alliance_id)
        setting.joint_ban_enabled = enabled
        setting.updated_at = dt.datetime.now(dt.UTC)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=member.alliance_id,
            action="toggle_joint_ban",
            operator_user_id=operator_user_id,
            payload={"enabled": enabled},
        )
        await session.flush()
        return setting

    @classmethod
    async def add_joint_ban_entry(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
        target_user_id: int,
        reason: str | None = None,
        punishment_type: str = "ban",
    ) -> GroupAllianceBanPool:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise ValidationError("当前群未加入联盟，无法使用联合封禁。")
        if punishment_type not in {"ban", "mute"}:
            raise ValidationError("无效的联盟处罚类型")
        await session.execute(select(GroupAlliance.alliance_id).where(
            GroupAlliance.alliance_id == member.alliance_id,
        ).with_for_update())
        if await cls.get_member(session,chat_id) is None:
            raise ValidationError('当前群已退出联盟，未写入处罚池。')
        from backend.shared.services.user_service import ensure_user
        await ensure_user(session, user_id=target_user_id, username=None, first_name=None, last_name=None, language_code=None)

        stmt: Select[tuple[GroupAllianceBanPool]] = select(GroupAllianceBanPool).where(
            GroupAllianceBanPool.alliance_id == member.alliance_id,
            GroupAllianceBanPool.target_user_id == target_user_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            await cls._upgrade_joint_entry(session, existing, chat_id=chat_id,
                operator_user_id=operator_user_id, punishment_type=punishment_type)
            return existing

        item = GroupAllianceBanPool(
            alliance_id=member.alliance_id,
            target_user_id=target_user_id,
            source_chat_id=chat_id,
            source_operator_user_id=operator_user_id,
            reason=reason,
            punishment_type=punishment_type,
        )
        session.add(item)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=member.alliance_id,
            action="joint_ban_add",
            operator_user_id=operator_user_id,
            payload={"target_user_id": target_user_id, "reason": reason, "punishment_type": punishment_type},
        )
        await session.flush()
        return item

    @classmethod
    async def _upgrade_joint_entry(cls, session, entry, *, chat_id: int, operator_user_id: int, punishment_type: str):
        if entry.punishment_type != "mute" or punishment_type != "ban":
            return
        entry.punishment_type = "ban"
        await cls.append_audit(session, chat_id=chat_id, alliance_id=entry.alliance_id,
            action="joint_ban_upgrade", operator_user_id=operator_user_id,
            payload={"target_user_id": entry.target_user_id, "from": "mute", "to": "ban"})
        await session.flush()

    @classmethod
    async def get_joint_ban_hit(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        target_user_id: int,
    ) -> tuple[GroupAllianceSetting, GroupAllianceBanPool] | None:
        setting = await cls.get_setting(session, chat_id)
        if setting is None or not setting.joint_ban_enabled:
            return None

        item = (
            await session.execute(
                select(GroupAllianceBanPool).where(
                    GroupAllianceBanPool.alliance_id == setting.alliance_id,
                    GroupAllianceBanPool.target_user_id == target_user_id,
                    select(GroupAllianceMember.id).where(GroupAllianceMember.chat_id==chat_id,
                        GroupAllianceMember.alliance_id==setting.alliance_id,GroupAllianceMember.status=='active').exists(),
                )
            )
        ).scalar_one_or_none()
        if item is None:
            return None
        return setting, item

    @classmethod
    async def list_joint_ban_entries(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        limit: int = 20,
    ) -> list[GroupAllianceBanPool]:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise NotFoundError("当前群尚未加入联盟。")
        result = await session.execute(
            select(GroupAllianceBanPool)
            .where(GroupAllianceBanPool.alliance_id == member.alliance_id)
            .order_by(GroupAllianceBanPool.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def remove_joint_ban_entry(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
        entry_id: int,
    ) -> GroupAllianceBanPool:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise NotFoundError("当前群尚未加入联盟。")

        await session.execute(select(GroupAlliance.alliance_id).where(GroupAlliance.alliance_id==member.alliance_id).with_for_update())
        if await cls.get_member(session,chat_id) is None:
            raise NotFoundError('当前群已退出联盟。')
        item = (
            await session.execute(
                select(GroupAllianceBanPool).where(
                    GroupAllianceBanPool.id == entry_id,
                    GroupAllianceBanPool.alliance_id == member.alliance_id,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("联合封禁条目不存在。")

        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=member.alliance_id,
            action="joint_ban_remove",
            operator_user_id=operator_user_id,
            payload={
                "entry_id": entry_id,
                "target_user_id": item.target_user_id,
                "source_chat_id": item.source_chat_id,
                "reason": item.reason,
            },
        )
        await session.delete(item)
        await session.flush()
        return item
