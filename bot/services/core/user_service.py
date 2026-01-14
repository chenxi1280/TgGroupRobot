from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import TgUser
from bot.services.base import ServiceBase


async def ensure_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    language_code: str | None,
) -> TgUser:
    """
    确保用户存在，不存在则创建，存在则更新信息

    Args:
        session: 数据库会话
        user_id: Telegram 用户 ID
        username: 用户名
        first_name: 名
        last_name: 姓
        language_code: 语言代码

    Returns:
        TgUser: 用户对象
    """
    user = await ServiceBase._get_by_id(session, TgUser, user_id)
    if user is None:
        user = TgUser(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
        )
        session.add(user)
        await session.flush()
        return user

    await ServiceBase._update_entity(
        session,
        user,
        {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "language_code": language_code,
            "updated_at": dt.datetime.now(dt.UTC),
        },
    )
    return user





