from __future__ import annotations

from telegram import Bot
from telegram.error import TelegramError

from bot.db.session import Database
from bot.models.core import TgChat


async def get_user_managed_chats(
    db: Database,
    user_id: int,
    bot: Bot,
) -> list[tuple[int, str, bool]]:
    """
    获取用户管理的群组列表

    返回: [(chat_id, title, is_admin), ...]
    """
    result = []

    # 从数据库获取所有 bot 所在的群组
    async with db.session_factory() as session:
        from sqlalchemy import select

        stmt = select(TgChat).where(
            TgChat.type.in_(["group", "supergroup"])
        )
        db_result = await session.execute(stmt)
        chats = list(db_result.scalars().all())

        for chat in chats:
            try:
                # 检查用户是否是该群组的管理员
                chat_member = await bot.get_chat_member(chat.id, user_id)

                from telegram import ChatMemberAdministrator, ChatMemberOwner

                is_admin = isinstance(chat_member, (ChatMemberAdministrator, ChatMemberOwner))

                if is_admin:
                    result.append((chat.id, chat.title or f"群组{chat.id}", True))
                else:
                    # 用户是群组成员但不是管理员（可选显示）
                    pass

            except TelegramError:
                # bot 不在该群组或无法获取信息，跳过
                pass

    return result


async def set_user_current_chat(
    db: Database,
    user_id: int,
    chat_id: int,
) -> bool:
    """设置用户当前管理的群组"""
    async with db.session_factory() as session:
        from bot.models.core import ConversationState, TgChat

        # 先确保私聊记录存在于 tg_chats 中
        from sqlalchemy import select

        private_chat_stmt = select(TgChat).where(TgChat.id == user_id)
        private_chat_result = await session.execute(private_chat_stmt)
        private_chat = private_chat_result.scalar_one_or_none()

        if private_chat is None:
            # 创建私聊记录
            private_chat = TgChat(
                id=user_id,
                type="private",
                title=None,  # 私聊没有 title
            )
            session.add(private_chat)
            await session.flush()

        # 查找现有状态
        stmt = select(ConversationState).where(
            ConversationState.user_id == user_id,
            ConversationState.chat_id == user_id,  # 私聊中的状态
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()

        if state:
            # 更新为选中的群组
            state.chat_id = chat_id
            state.state_type = "selected_chat"
            state.state_data = {"managed_chat_id": chat_id}
        else:
            # 创建新状态
            state = ConversationState(
                chat_id=user_id,  # 存储在用户私聊上下文
                user_id=user_id,
                state_type="selected_chat",
                state_data={"managed_chat_id": chat_id},
            )
            session.add(state)

        await session.commit()
        return True


async def get_user_current_chat(
    db: Database,
    user_id: int,
) -> int | None:
    """获取用户当前选中的群组"""
    async with db.session_factory() as session:
        from bot.models.core import ConversationState
        from sqlalchemy import select

        stmt = select(ConversationState).where(
            ConversationState.user_id == user_id,
            ConversationState.chat_id == user_id,
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()

        if state and state.state_data:
            return state.state_data.get("managed_chat_id")
        return None
