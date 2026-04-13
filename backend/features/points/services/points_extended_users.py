from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatMember, TgUser
from backend.shared.services.user_service import ensure_user


class PointsExtendedUserMixin:
    @staticmethod
    async def is_chat_member(session: AsyncSession, chat_id: int, user_id: int) -> bool:
        result = await session.execute(
            select(ChatMember.id).where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id).limit(1)
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
        result = await session.execute(select(TgUser.id).where(func.lower(TgUser.username) == username))
        return result.scalar_one_or_none()
