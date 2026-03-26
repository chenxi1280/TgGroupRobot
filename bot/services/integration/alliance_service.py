from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.alliance import (
    GroupAlliance,
    GroupAllianceAudit,
    GroupAllianceBanPool,
    GroupAllianceMember,
    GroupAllianceSetting,
)
from bot.models.core import TgChat
from bot.services.base import NotFoundError, ValidationError


class AllianceService:
    NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff\- ]{2,32}$")

    @staticmethod
    def generate_invite_code() -> str:
        return secrets.token_urlsafe(6).replace("-", "").replace("_", "").upper()[:10]

    @staticmethod
    def hash_invite_code(code: str) -> str:
        return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()

    @classmethod
    def validate_alliance_name(cls, name: str) -> str:
        normalized = name.strip()
        if not cls.NAME_PATTERN.fullmatch(normalized):
            raise ValidationError("联盟名称需为 2-32 位，可包含中文、字母、数字、空格和 - _")
        return normalized

    @staticmethod
    async def get_member(session: AsyncSession, chat_id: int) -> GroupAllianceMember | None:
        result = await session.execute(
            select(GroupAllianceMember).where(
                GroupAllianceMember.chat_id == chat_id,
                GroupAllianceMember.status == "active",
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_alliance_by_chat(session: AsyncSession, chat_id: int) -> GroupAlliance | None:
        member = await AllianceService.get_member(session, chat_id)
        if member is None:
            return None
        return await session.get(GroupAlliance, member.alliance_id)

    @staticmethod
    async def get_setting(session: AsyncSession, chat_id: int) -> GroupAllianceSetting | None:
        return await session.get(GroupAllianceSetting, chat_id)

    @staticmethod
    async def ensure_setting(session: AsyncSession, chat_id: int, alliance_id: int) -> GroupAllianceSetting:
        setting = await session.get(GroupAllianceSetting, chat_id)
        if setting is None:
            setting = GroupAllianceSetting(chat_id=chat_id, alliance_id=alliance_id, joint_ban_enabled=False)
            session.add(setting)
            await session.flush()
            return setting
        setting.alliance_id = alliance_id
        return setting

    @staticmethod
    async def append_audit(
        session: AsyncSession,
        *,
        chat_id: int,
        alliance_id: int | None,
        action: str,
        operator_user_id: int | None,
        payload: dict | None = None,
        result: str = "success",
    ) -> None:
        session.add(
            GroupAllianceAudit(
                chat_id=chat_id,
                alliance_id=alliance_id,
                action=action,
                operator_user_id=operator_user_id,
                payload=payload or {},
                result=result,
            )
        )
        await session.flush()

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
        member.status = "left"
        setting = await cls.get_setting(session, chat_id)
        if setting is not None:
            await session.delete(setting)

        if alliance.owner_chat_id == chat_id and len(active_members) <= 1:
            await session.delete(alliance)
        else:
            alliance.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()

    @classmethod
    async def list_members(cls, session: AsyncSession, alliance_id: int) -> list[tuple[GroupAllianceMember, TgChat | None]]:
        result = await session.execute(
            select(GroupAllianceMember, TgChat)
            .join(TgChat, TgChat.id == GroupAllianceMember.chat_id)
            .where(
                GroupAllianceMember.alliance_id == alliance_id,
                GroupAllianceMember.status == "active",
            )
            .order_by(GroupAllianceMember.joined_at.asc())
        )
        return [(member, chat) for member, chat in result.all()]

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
    ) -> GroupAllianceBanPool:
        member = await cls.get_member(session, chat_id)
        if member is None:
            raise ValidationError("当前群未加入联盟，无法使用联合封禁。")

        stmt: Select[tuple[GroupAllianceBanPool]] = select(GroupAllianceBanPool).where(
            GroupAllianceBanPool.alliance_id == member.alliance_id,
            GroupAllianceBanPool.target_user_id == target_user_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        item = GroupAllianceBanPool(
            alliance_id=member.alliance_id,
            target_user_id=target_user_id,
            source_chat_id=chat_id,
            source_operator_user_id=operator_user_id,
            reason=reason,
        )
        session.add(item)
        await cls.append_audit(
            session,
            chat_id=chat_id,
            alliance_id=member.alliance_id,
            action="joint_ban_add",
            operator_user_id=operator_user_id,
            payload={"target_user_id": target_user_id, "reason": reason},
        )
        await session.flush()
        return item

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
                )
            )
        ).scalar_one_or_none()
        if item is None:
            return None
        return setting, item
