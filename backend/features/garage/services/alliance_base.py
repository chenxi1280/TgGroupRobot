from __future__ import annotations

import hashlib
import re
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.alliance import (
    GroupAlliance,
    GroupAllianceAudit,
    GroupAllianceMember,
    GroupAllianceSetting,
)
from backend.platform.db.schema.models.core import TgChat
from backend.shared.services.base import ValidationError


class AllianceBaseMixin:
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

    @classmethod
    async def get_alliance_by_chat(cls, session: AsyncSession, chat_id: int) -> GroupAlliance | None:
        member = await cls.get_member(session, chat_id)
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
