from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.garage_auth_service import GarageAuthService
from backend.platform.db.schema.models.alliance import GroupAlliance, GroupAllianceMember
from backend.shared.services.base import NotFoundError, ValidationError


class AllianceLifecycleMixin:
    @classmethod
    async def create_alliance(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
        name: str,
    ) -> tuple[GroupAlliance, str]:
        normalized = cls.validate_alliance_name(name)
        existing_member = await cls.get_member(session, chat_id)
        if existing_member is not None:
            raise ValidationError("当前群已经加入联盟，无法重复创建。")

        exists = await session.execute(select(GroupAlliance).where(GroupAlliance.name == normalized))
        if exists.scalar_one_or_none() is not None:
            raise ValidationError("联盟名称已存在，请更换一个名字。")

        invite_code = cls.generate_invite_code()
        alliance = GroupAlliance(
            name=normalized,
            owner_chat_id=chat_id,
            invite_code_hash=cls.hash_invite_code(invite_code),
        )
        session.add(alliance)
        await session.flush()

        session.add(
            GroupAllianceMember(
                alliance_id=alliance.alliance_id,
                chat_id=chat_id,
                status="active",
            )
        )
        await cls.ensure_setting(session, chat_id, alliance.alliance_id)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=alliance.alliance_id,
            action="create",
            operator_user_id=operator_user_id,
            payload={"name": normalized},
        )
        return alliance, invite_code

    @classmethod
    async def rotate_invite_code(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
    ) -> str:
        alliance = await cls.get_alliance_by_chat(session, chat_id)
        if alliance is None:
            raise NotFoundError("当前群尚未加入联盟。")
        if alliance.owner_chat_id != chat_id:
            raise ValidationError("只有创建群可以重置联盟邀请码。")
        invite_code = cls.generate_invite_code()
        alliance.invite_code_hash = cls.hash_invite_code(invite_code)
        alliance.updated_at = dt.datetime.now(dt.UTC)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=alliance.alliance_id,
            action="invite_rotate",
            operator_user_id=operator_user_id,
            payload={"rotated": True},
        )
        await session.flush()
        return invite_code

    @classmethod
    async def join_alliance(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
        invite_code: str,
    ) -> GroupAlliance:
        if await cls.get_member(session, chat_id) is not None:
            raise ValidationError("当前群已在联盟中，请先退出后再加入。")

        code_hash = cls.hash_invite_code(invite_code)
        result = await session.execute(
            select(GroupAlliance)
            .where(GroupAlliance.invite_code_hash == code_hash)
            .with_for_update()
        )
        alliance = result.scalar_one_or_none()
        if alliance is None:
            raise ValidationError("联盟邀请码无效。")
        if alliance.invite_code_expire_at and alliance.invite_code_expire_at <= dt.datetime.now(dt.UTC):
            raise ValidationError("联盟邀请码已过期。")

        count_result = await session.execute(
            select(func.count(GroupAllianceMember.id)).where(
                GroupAllianceMember.alliance_id == alliance.alliance_id,
                GroupAllianceMember.status == "active",
            )
        )
        if int(count_result.scalar_one() or 0) >= 50:
            raise ValidationError("联盟成员数量已达上限。")

        await GarageAuthService.merge_local_certified_teachers_into_pool(
            session,
            source_chat_id=chat_id,
            pool_chat_id=alliance.owner_chat_id,
            operator_user_id=operator_user_id,
        )
        session.add(
            GroupAllianceMember(
                alliance_id=alliance.alliance_id,
                chat_id=chat_id,
                status="active",
            )
        )
        await cls.ensure_setting(session, chat_id, alliance.alliance_id)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=alliance.alliance_id,
            action="join",
            operator_user_id=operator_user_id,
            payload={"joined": True},
        )
        await session.flush()
        return alliance

    @classmethod
    async def leave_alliance(
        cls,
        session: AsyncSession,
        *,
        chat_id: int,
        operator_user_id: int,
    ) -> None:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise NotFoundError("当前群尚未加入联盟。")
        alliance = await session.get(GroupAlliance, member.alliance_id)
        if alliance is None:
            raise NotFoundError("联盟不存在。")

        active_members = await cls.list_members(session, alliance.alliance_id)
        if alliance.owner_chat_id == chat_id and len(active_members) > 1:
            raise ValidationError("创建群仍有其他成员时不能直接退出联盟。")

        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=alliance.alliance_id,
            action="leave",
            operator_user_id=operator_user_id,
            payload={"left": True},
        )
        if alliance.owner_chat_id != chat_id:
            await GarageAuthService.sync_local_certified_teachers_from_effective_pool(
                session,
                chat_id=chat_id,
                operator_user_id=operator_user_id,
            )
        member.status = "left"
        setting = await cls.get_setting(session, chat_id)
        if setting is not None:
            await session.delete(setting)

        if alliance.owner_chat_id == chat_id and len(active_members) <= 1:
            await session.delete(alliance)
        else:
            alliance.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
