from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.base import ServiceBase


async def _bind_pending_teacher_sources(session: AsyncSession, user: TgUser) -> None:
    if not (user.username or "").strip():
        return
    from backend.features.garage.services.teacher_search_channel_index import bind_pending_source_posts_for_user

    await bind_pending_source_posts_for_user(session, user)


async def ensure_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    *, first_name: str | None,
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
        await _bind_pending_teacher_sources(session, user)
        return user

    await ServiceBase._update_entity(
        session,
        user,
        {
            # 仅在新值非空时覆盖，避免后台流程把用户资料抹成 NULL
            "username": username if username is not None else user.username,
            "first_name": first_name if first_name is not None else user.first_name,
            "last_name": last_name if last_name is not None else user.last_name,
            "language_code": language_code if language_code is not None else user.language_code,
            "updated_at": dt.datetime.now(dt.UTC),
        },
    )
    await _bind_pending_teacher_sources(session, user)
    return user



