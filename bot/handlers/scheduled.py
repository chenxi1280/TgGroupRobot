from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.enums import ConversationStateType, ScheduleType
from bot.models.core import ScheduledMessage
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.scheduled_message_service import (
    create_scheduled_message,
    delete_scheduled_message,
    get_chat_scheduled_messages,
    get_scheduled_message,
    toggle_scheduled_message,
    update_scheduled_message,
    CreateResult,
)
from bot.services.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.telegram_perm import is_user_admin
from bot.services.user_service import ensure_user


# ============================================
# 回调处理器
# ============================================

async def scheduled_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """定时消息菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的定时消息管理 - 返回到管理面板
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        from bot.services.chat_group_service import get_user_managed_chats
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return

        # 返回到管理面板
        chats = await get_user_managed_chats(db, user.id, context.bot)
        from bot.handlers.admin import _show_private_admin_menu
        await _show_private_admin_menu(update, context, target_chat_id, chats)
        return

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        messages = await get_chat_scheduled_messages(session, chat.id)
        await session.commit()

    text = f"⏰ [{chat.title}] 定时消息\n\n"
    if messages:
        active_count = sum(1 for m in messages if m.is_active)
        text += f"总计: {len(messages)} 条消息  |  激活: {active_count} 条\n\n"
        for msg in messages[:10]:
            status = "🟢" if msg.is_active else "🔴"
            content_preview = msg.content[:30] + "..." if len(msg.content) > 30 else msg.content
            text += f"{status} [{msg.id}] {content_preview}\n"
            if msg.schedule_type != ScheduleType.none.value:
                text += f"    间隔: {_get_schedule_label(msg.schedule_type, msg.interval_minutes)}\n"
        if len(messages) > 10:
            text += f"\n... 还有 {len(messages) - 10} 条"
    else:
        text += "暂无定时消息"

    from bot.keyboards.scheduled import scheduled_menu_keyboard

    await q.edit_message_text(text, reply_markup=scheduled_menu_keyboard())


async def scheduled_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建定时消息流程"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    data = q.data or ""

    # 私聊中的定时消息创建 - 优先从 callback_data 获取目标群组ID
    target_chat_id = None
    target_chat_title = None
    if chat.type == "private":
        # 优先从 callback_data 提取 chat_id
        if data.startswith("scheduled:create:"):
            parts = data.split(":")
            if len(parts) >= 3:
                try:
                    target_chat_id = int(parts[2])
                except ValueError:
                    pass

        # 如果 callback_data 中没有 chat_id，从数据库获取
        if target_chat_id is None:
            from bot.services.chat_group_service import get_user_current_chat
            from bot.models.core import TgChat
            from sqlalchemy import select
            db: Database = context.application.bot_data["db"]
            target_chat_id = await get_user_current_chat(db, user.id)
            if target_chat_id is None:
                await q.edit_message_text("请先选择一个群组")
                return

        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return

        # 获取群组信息用于后续操作
        from bot.models.core import TgChat
        from sqlalchemy import select
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
            chat_result = await session.execute(chat_stmt)
            target_chat_obj = chat_result.scalar_one_or_none()
            target_chat_title = target_chat_obj.title if target_chat_obj else f"群组{target_chat_id}"
            await session.commit()
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("需要管理员权限。")
            return
        target_chat_id = chat.id
        target_chat_title = chat.title

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )

        # 设置状态：等待输入配置，保存目标群组ID
        await set_user_state(
            session,
            chat_id=target_chat_id,  # 使用目标群组ID保存状态
            user_id=user.id,
            state_type=ConversationStateType.scheduled_create.value,
            state_data={"step": "content", "target_chat_id": target_chat_id},
        )
        await session.commit()

    text = "⏰ 创建定时消息  ( /cancel 取消)\n\n"
    text += "请按以下格式发送消息配置：\n\n"
    text += "```\n"
    text += "消息内容\n"
    text += "定时类型: every_5_minutes\n"
    text += "初始延迟: 0（分钟，立即开始）\n"
    text += "```\n\n"
    text += "定时类型选项:\n"
    text += "• none - 一次性消息\n"
    text += "• every_minute - 每分钟\n"
    text += "• every_5_minutes - 每5分钟\n"
    text += "• every_15_minutes - 每15分钟\n"
    text += "• every_30_minutes - 每30分钟\n"
    text += "• every_hour - 每小时\n"
    text += "• every_6_hours - 每6小时\n"
    text += "• every_12_hours - 每12小时\n"
    text += "• every_day - 每天\n\n"
    text += "示例:\n"
    text += "```\n"
    text += "大家好，这是定时测试消息！\n"
    text += "定时类型: every_hour\n"
    text += "初始延迟: 5\n"
    text += "```"

    await q.edit_message_text(text, parse_mode="Markdown")


async def scheduled_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换定时消息状态回调"""
    if update.callback_query is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    if chat.type == "private":
        return

    # 解析消息ID
    data = q.data
    if not data.startswith("scheduled_toggle_"):
        return

    try:
        message_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await toggle_scheduled_message(session, message_id)
        await session.commit()

    if result.success:
        await q.answer("状态已切换")
        # 刷新列表
        await scheduled_menu_callback(update, context)
    else:
        await q.answer("消息不存在", show_alert=True)


async def scheduled_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除定时消息回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return

    if not await is_user_admin(context, chat.id, user.id):
        await q.answer("需要管理员权限", show_alert=True)
        return

    # 解析消息ID
    data = q.data
    if not data.startswith("scheduled_delete_"):
        return

    try:
        message_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_scheduled_message(session, message_id)
        await session.commit()

    if success:
        await q.answer("消息已删除")
        await scheduled_menu_callback(update, context)
    else:
        await q.answer("删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================

async def scheduled_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理定时消息创建流程中的消息"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    # 只在私聊或群聊中处理
    if not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取用户状态 - 从目标群组获取状态（私聊模式下）
        state_data_dict = None
        if chat.type == "private":
            # 私聊模式：从用户当前选中的群组获取状态
            from bot.services.chat_group_service import get_user_current_chat
            target_chat_id = await get_user_current_chat(db, user.id)
            if target_chat_id:
                state = await get_user_state(session, chat_id=target_chat_id, user_id=user.id)
        else:
            # 群聊模式：从当前群组获取状态
            state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

        if state is None or state.state_type != ConversationStateType.scheduled_create.value:
            await session.commit()
            return

        step = state.state_data.get("step")

        if step == "content":
            await _parse_scheduled_config(update, session, state, text)
        else:
            await session.commit()


async def _parse_scheduled_config(update: Update, session, state: object, text: str) -> None:
    """解析定时消息配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("配置格式不完整")

        # 解析消息内容（第一行到包含"定时类型:"的前一行）
        content_lines = []
        schedule_type = None
        initial_delay = 0

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("定时类型:"):
                schedule_type = line.split(":", 1)[1].strip()
                i += 1
                break
            content_lines.append(line)
            i += 1

        content = "\n".join(content_lines).strip()
        if not content:
            raise ValueError("消息内容不能为空")

        if not schedule_type:
            raise ValueError("必须指定定时类型")

        # 解析初始延迟
        if i < len(lines):
            delay_line = lines[i].strip()
            if delay_line.startswith("初始延迟:"):
                try:
                    initial_delay = int(delay_line.split(":", 1)[1].strip())
                    if initial_delay < 0:
                        raise ValueError
                except ValueError:
                    raise ValueError("初始延迟必须是正整数")

        # 获取目标群组ID（从状态数据中获取）
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id

        # 创建定时消息
        result = await create_scheduled_message(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            content=content,
            schedule_type=schedule_type,
            initial_delay_minutes=initial_delay,
        )

        if not result.success:
            error_messages = {
                "invalid_content": "消息内容无效",
                "invalid_schedule_type": "定时类型无效",
                "invalid_interval": "间隔设置无效",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from bot.keyboards.admin import admin_main_menu

        reply_text = f"✅ 定时消息创建成功！\n\n"
        reply_text += f"📝 内容: {content[:50]}{'...' if len(content) > 50 else ''}\n"
        reply_text += f"⏰ 间隔: {_get_schedule_label(schedule_type, None)}\n"
        reply_text += f"🕐 首次发送: {result.message.next_send_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        reply_text += f"\n消息ID: {result.message.id}"

        await update.effective_message.reply_text(reply_text, reply_markup=admin_main_menu())

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


def _get_schedule_label(schedule_type: str, interval_minutes: int | None) -> str:
    """获取定时类型标签"""
    labels = {
        "none": "一次性消息",
        "every_minute": "每分钟",
        "every_5_minutes": "每5分钟",
        "every_15_minutes": "每15分钟",
        "every_30_minutes": "每30分钟",
        "every_hour": "每小时",
        "every_6_hours": "每6小时",
        "every_12_hours": "每12小时",
        "every_day": "每天",
        "custom": f"自定义({interval_minutes}分钟)" if interval_minutes else "自定义",
    }
    return labels.get(schedule_type, schedule_type)
