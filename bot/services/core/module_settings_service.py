from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, TgChat
from bot.services.base import ServiceBase
from bot.services.core.user_service import ensure_user


class ModuleSettingsService:
    """
    群配置统一自愈入口。

    目标是把各模块里反复出现的
    `ensure_chat -> ensure_user -> ensure_module_settings`
    模板收敛到一个中心方法里。
    """

    @staticmethod
    def _infer_chat_type(chat_id: int, chat_type: str | None) -> str:
        if chat_type:
            return chat_type
        return "supergroup" if chat_id < 0 else "private"

    @classmethod
    async def _ensure_chat(
        cls,
        session: AsyncSession,
        chat_id: int,
        chat_type: str | None = None,
        title: str | None = None,
    ) -> TgChat:
        inferred_type = cls._infer_chat_type(chat_id, chat_type)
        chat = await ServiceBase._get_by_id(session, TgChat, chat_id)
        if chat is None:
            chat = TgChat(id=chat_id, type=inferred_type, title=title)
            session.add(chat)
            await session.flush()
            return chat

        updates: dict[str, object] = {}
        next_title = title if title is not None else chat.title
        if chat.title != next_title:
            updates["title"] = next_title
        if chat.type != inferred_type:
            updates["type"] = inferred_type
        if updates:
            updates["updated_at"] = dt.datetime.now(dt.UTC)
            await ServiceBase._update_entity(session, chat, updates)
        return chat

    @classmethod
    async def ensure(
        cls,
        session: AsyncSession,
        chat_id: int,
        *,
        chat_type: str | None = None,
        title: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ) -> ChatSettings:
        """
        确保群、用户和群设置存在。

        chat_id=0 时返回一个临时对象，不写库，保留旧行为兼容。
        """
        if chat_id == 0:
            return ChatSettings(chat_id=0)

        await cls._ensure_chat(session, chat_id=chat_id, chat_type=chat_type, title=title)

        if user_id is not None:
            await ensure_user(
                session,
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )

        settings = await ServiceBase._get_by_filters(
            session,
            ChatSettings,
            {"chat_id": chat_id},
        )
        if settings is None:
            settings = ChatSettings(chat_id=chat_id)
            session.add(settings)
            await session.flush()
        return settings
