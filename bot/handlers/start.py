from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.admin import admin_main_menu
from bot.keyboards.chat_group import chat_group_list_keyboard
from bot.models.enums import ConversationStateType
from bot.services.chat_group_service import get_user_current_chat, get_user_managed_chats
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.state_service import clear_user_state, get_user_state
from bot.services.telegram_perm import is_user_admin
from bot.services.user_service import ensure_user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """上下文感知的 /start：根据用户状态返回不同内容"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        # 私聊中显示群组列表
        chats = await get_user_managed_chats(db, user.id, context.bot)
        current_chat_id = await get_user_current_chat(db, user.id)

        if not chats:
            await update.effective_message.reply_text(
                "👋 欢迎使用群管理 Bot！\n\n"
                "暂无群组，请先将 bot 添加到群组中，并确保你具有管理员权限。\n\n"
                "💡 添加 bot 到群组后，发送 /start 或点击下方按钮刷新列表。",
                reply_markup=chat_group_list_keyboard(chats, current_chat_id),
            )
        else:
            # 有当前选中的群组，显示该群组信息
            if current_chat_id:
                for cid, title, _ in chats:
                    if cid == current_chat_id:
                        await update.effective_message.reply_text(
                            f"👋 欢迎回来！\n\n"
                            f"📌 当前管理: {title}\n\n"
                            f"可以选择其他群组或进入群组设置。",
                            reply_markup=chat_group_list_keyboard(chats, current_chat_id),
                        )
                        return

            # 没有选中群组，显示列表
            await update.effective_message.reply_text(
                f"👋 欢迎使用群管理 Bot！\n\n"
                f"共 {len(chats)} 个群组\n"
                f"请选择要管理的群组：",
                reply_markup=chat_group_list_keyboard(chats, current_chat_id),
            )
        return

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        settings = await get_chat_settings(session, chat.id)

        # 检查用户是否有对话状态
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

        # 如果有状态，清除状态并返回首页
        if state is not None:
            await clear_user_state(session, chat_id=chat.id, user_id=user.id)
            await session.commit()
            # 如果是管理员，显示管理面板；否则显示普通提示
            if await is_user_admin(context, chat.id, user.id):
                await update.effective_message.reply_text(
                    f"设置[{chat.title}]群组，选择要更改的项目",
                    reply_markup=admin_main_menu(),
                )
            else:
                await update.effective_message.reply_text(t(settings.language, "start.group"))
            return

        # 没有状态：管理员显示管理面板，普通用户显示提示
        await session.commit()

    if await is_user_admin(context, chat.id, user.id):
        await update.effective_message.reply_text(
            f"设置[{chat.title}]群组，选择要更改的项目",
            reply_markup=admin_main_menu(),
        )
    else:
        await update.effective_message.reply_text(t(settings.language, "start.group"))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消当前流程，返回首页"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用该指令。")
        return

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        # 清除状态
        await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 返回首页
    if await is_user_admin(context, chat.id, user.id):
        await update.effective_message.reply_text(
            f"设置[{chat.title}]群组，选择要更改的项目",
            reply_markup=admin_main_menu(),
        )
    else:
        await update.effective_message.reply_text(t(settings.language, "start.group"))


async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理私聊中的普通文本消息"""
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return

    chat = update.effective_chat
    if chat.type != "private":
        return

    user = update.effective_user

    # 先检查用户是否有对话状态（如抽奖创建流程）
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        from bot.services.state_service import get_user_state

        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 如果有对话状态，不做处理（让其他专门的消息处理器处理）
    if state is not None:
        return

    # 没有对话状态，显示群组列表
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await get_user_current_chat(db, user.id)

    if not chats:
        await update.effective_message.reply_text(
            "📋 群组管理\n\n"
            "暂无群组，请先将 bot 添加到群组中。\n\n"
            "💡 提示：添加 bot 到群组后，发送 /start 刷新列表。",
        )
    else:
        text = f"📋 群组列表\n\n"
        text += f"共 {len(chats)} 个群组\n"
        text += f"请选择要管理的群组："
        await update.effective_message.reply_text(
            text,
            reply_markup=chat_group_list_keyboard(chats, current_chat_id),
        )





