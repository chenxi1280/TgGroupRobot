from __future__ import annotations

from telegram import Bot
from telegram import ChatMemberAdministrator, ChatMemberOwner
from telegram.error import TelegramError
from sqlalchemy import select
import structlog

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ConversationState, TgChat
from backend.shared.services.user_service import ensure_user

log = structlog.get_logger(__name__)


async def _load_group_chats(db: Database) -> list[TgChat]:
    async with db.session_factory() as session:
        result = await session.execute(select(TgChat).where(TgChat.type.in_(["group", "supergroup"])))
        return list(result.scalars().all())


async def _managed_chat_entry(bot: Bot, chat: TgChat, user_id: int) -> tuple[int, str, bool] | None:
    try:
        member = await bot.get_chat_member(chat.id, user_id)
    except TelegramError as exc:
        log.warning("failed_to_check_chat_membership", user_id=user_id, chat_id=chat.id, error=str(exc))
        return None
    if not isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
        return None
    return chat.id, chat.title or f"群组{chat.id}", True


async def _ensure_private_chat(session, user_id: int) -> None:
    if await session.get(TgChat, user_id) is not None:
        return
    session.add(TgChat(id=user_id, type="private", title=None))
    await session.flush()


async def _set_selected_chat_state(session, user_id: int, chat_id: int) -> None:
    result = await session.execute(select(ConversationState).where(
        ConversationState.user_id == user_id,
        ConversationState.chat_id == user_id,
    ))
    state = result.scalar_one_or_none()
    if state is None:
        session.add(ConversationState(
            chat_id=user_id, user_id=user_id, state_type="selected_chat",
            state_data={"managed_chat_id": chat_id},
        ))
        return
    state.state_data = {"managed_chat_id": chat_id}


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
    return (
        f"👋 欢迎回来！\n\n"
        f"📌 当前管理: {chat_title}\n\n"
        "新群或功能异常时，建议先点「健康检查」确认机器人权限和关键配置。\n"
        "配置类功能完成后，请先预览，再到群内测试一次。"
    )


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
        f"欢迎使用 @{bot_username}\n\n"
        "管理员配置流程：\n"
        "1. 先确认机器人已设为群管理员，并具备删消息、禁言、邀请链接等必要权限。\n"
        "2. 点击下方「前往设置」进入机器人私聊设置页。\n"
        "3. 在私聊里确认当前管理群组后，建议先运行「健康检查」。\n"
        "4. 配置功能后先预览，再回到群内用测试账号触发一次。"
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
    log.info("get_user_managed_chats_start", user_id=user_id)
    chats = await _load_group_chats(db)
    entries = [await _managed_chat_entry(bot, chat, user_id) for chat in chats]
    result = [entry for entry in entries if entry is not None]
    log.info("get_user_managed_chats_complete", user_id=user_id, result_count=len(result))
    return result


async def set_user_current_chat(
    db: Database,
    user_id: int,
    chat_id: int,
) -> bool:
    """设置用户当前管理的群组"""
    async with db.session_factory() as session:
        await ensure_user(
            session,
            user_id=user_id,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )

        await _ensure_private_chat(session, user_id)
        await _set_selected_chat_state(session, user_id, chat_id)
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
