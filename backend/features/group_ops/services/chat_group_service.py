from __future__ import annotations

from telegram import Bot
from telegram.error import TelegramError

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat
from backend.shared.services.user_service import ensure_user


# ==================== 格式化函数 ====================


def format_private_chat_welcome(bot_username: str, has_chats: bool = False) -> str:
    """
    格式化私聊欢迎消息

    Args:
        bot_username: 机器人用户名
        has_chats: 是否有可用群组

    Returns:
        格式化后的欢迎消息文本
    """
    if not has_chats:
        return (
            "👋 欢迎使用群管理 Bot！\n\n"
            "暂无群组，请先将 bot 添加到群组中，并确保你具有管理员权限。\n\n"
            "💡 添加 bot 到群组后，发送 /start 或点击下方按钮刷新列表。"
        )
    return "👋 欢迎使用群管理 Bot！\n\n"


def format_private_chat_current_title(chat_title: str) -> str:
    """
    格式化私聊中当前管理群组的信息

    Args:
        chat_title: 当前管理的群组标题

    Returns:
        格式化后的群组信息文本
    """
    return f"👋 欢迎回来！\n\n📌 当前管理: {chat_title}\n\n可以选择其他群组或进入群组设置。"


def format_private_chat_list(chat_count: int) -> str:
    """
    格式化私聊群组列表消息

    Args:
        chat_count: 群组数量

    Returns:
        格式化后的群组列表文本
    """
    return f"👋 欢迎使用群管理 Bot！\n\n共 {chat_count} 个群组\n请选择要管理的群组："


def format_group_guide_message(bot_username: str) -> str:
    """
    格式化群组引导消息

    Args:
        bot_username: 机器人用户名

    Returns:
        格式化后的引导消息文本
    """
    return (
        f"欢迎使用@{bot_username}:\n\n"
        f"1) 点击下方按钮选择设置（仅限管理员）\n"
        f"2) 点击机器人对话框底部[开始]按钮\n\n"
        f"人员按下面的开始按钮调整到私聊机器界面进行管理群聊"
    )


def format_empty_chat_list_hint() -> str:
    """
    格式化空群组列表提示消息

    Returns:
        格式化后的提示消息文本
    """
    return (
        "📋 群组管理\n\n"
        "暂无群组，请先将 bot 添加到群组中。\n\n"
        "💡 提示：添加 bot 到群组后，发送 /start 刷新列表。"
    )


async def get_user_managed_chats(
    db: Database,
    user_id: int,
    bot: Bot,
) -> list[tuple[int, str, bool]]:
    """
    获取用户管理的群组列表

    返回: [(chat_id, title, is_admin), ...]
    """
    import structlog
    log = structlog.get_logger(__name__)

    result = []

    log.info("get_user_managed_chats_start", user_id=user_id)

    try:
        # 从数据库获取所有 bot 所在的群组
        async with db.session_factory() as session:
            from sqlalchemy import select

            stmt = select(TgChat).where(
                TgChat.type.in_(["group", "supergroup"])
            )
            log.info("get_user_managed_chats_executing_query", user_id=user_id)
            db_result = await session.execute(stmt)
            chats = list(db_result.scalars().all())

            log.info("get_user_managed_chats_found_chats", user_id=user_id, chat_count=len(chats))

            for chat in chats:
                try:
                    log.info("checking_chat_membership", user_id=user_id, chat_id=chat.id)
                    # 检查用户是否是该群组的管理员
                    chat_member = await bot.get_chat_member(chat.id, user_id)

                    from telegram import ChatMemberAdministrator, ChatMemberOwner

                    is_admin = isinstance(chat_member, (ChatMemberAdministrator, ChatMemberOwner))

                    log.info("chat_membership_checked", user_id=user_id, chat_id=chat.id, is_admin=is_admin)

                    if is_admin:
                        title = chat.title or f"群组{chat.id}"
                        result.append((chat.id, title, True))
                    else:
                        # 用户是群组成员但不是管理员（可选显示）
                        pass

                except TelegramError as e:
                    # bot 不在该群组或无法获取信息，跳过
                    log.warning("failed_to_check_chat_membership", user_id=user_id, chat_id=chat.id, error=str(e))

        log.info("get_user_managed_chats_complete", user_id=user_id, result_count=len(result))
    except Exception as e:
        log.exception("get_user_managed_chats_error", user_id=user_id, error=str(e))
        return []

    return result


async def set_user_current_chat(
    db: Database,
    user_id: int,
    chat_id: int,
) -> bool:
    """设置用户当前管理的群组"""
    async with db.session_factory() as session:
        from backend.platform.db.schema.models.core import ConversationState, TgChat
        from sqlalchemy import select

        # 确保用户存在（conversation_states.user_id 外键依赖 tg_users）
        await ensure_user(
            session,
            user_id=user_id,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )

        # 先确保私聊记录存在于 tg_chats 中
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

        # 查找或创建私聊状态（保留它，不删除）
        private_state_stmt = select(ConversationState).where(
            ConversationState.user_id == user_id,
            ConversationState.chat_id == user_id,
        )
        private_state_result = await session.execute(private_state_stmt)
        private_state = private_state_result.scalar_one_or_none()

        if private_state is None:
            # 创建私聊状态，保存 managed_chat_id
            private_state = ConversationState(
                chat_id=user_id,  # 保持为私聊ID
                user_id=user_id,
                state_type="selected_chat",
                state_data={"managed_chat_id": chat_id},
            )
            session.add(private_state)
        else:
            # 更新现有私聊状态的 managed_chat_id
            private_state.state_data = {"managed_chat_id": chat_id}

        await session.commit()
        return True


async def get_user_current_chat(
    db: Database,
    user_id: int,
) -> int | None:
    """获取用户当前选中的群组"""
    async with db.session_factory() as session:
        from backend.platform.db.schema.models.core import ConversationState
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
