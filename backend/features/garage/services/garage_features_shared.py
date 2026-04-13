from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.base import ServiceBase, ValidationError


def _normalize_username_or_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValidationError("输入内容不能为空。")
    return value[1:] if value.startswith("@") else value


async def _resolve_user(session: AsyncSession, raw: str) -> TgUser:
    value = _normalize_username_or_id(raw)
    if value.lstrip("-").isdigit():
        user = await ServiceBase._get_by_id(session, TgUser, int(value))
    else:
        result = await session.execute(select(TgUser).where(TgUser.username == value))
        user = result.scalar_one_or_none()
    if user is None:
        raise ValidationError("未找到该用户，请先让对方与机器人产生交互。")
    return user
