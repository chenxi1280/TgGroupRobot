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


async def scheduled_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """定时消息列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    data = q.data or ""

    # 获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        # 从 callback_data 提取 chat_id
        if data.startswith("scheduled:list:"):
            parts = data.split(":")
            if len(parts) >= 3:
                try:
                    target_chat_id = int(parts[2])
                except ValueError:
                    pass

        # 如果 callback_data 中没有，从数据库获取
        if target_chat_id is None:
            db: Database = context.application.bot_data["db"]
            target_chat_id = await get_user_current_chat(db, user.id)
            if target_chat_id is None:
                await q.edit_message_text("请先选择一个群组")
                return
    else:
        target_chat_id = chat.id

    # 获取定时消息列表
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        messages = await get_chat_scheduled_messages(session, target_chat_id)
        await session.commit()

    # 构建列表文本
    text = f"📋 定时消息列表\n\n"
    if messages:
        active_count = sum(1 for m in messages if m.is_active)
        text += f"总计: {len(messages)} 条  |  激活: {active_count} 条\n\n"

        for msg in messages:
            status = "🟢 激活" if msg.is_active else "🔴 暂停"
            repeat_text = "🔄 重复" if msg.repeat_enabled else "➡️ 一次性"
            content_preview = msg.content[:30] + "..." if len(msg.content) > 30 else msg.content
            text += f"{status} {repeat_text} [{msg.id}]\n"
            text += f"    {content_preview}\n"
            if msg.schedule_type != ScheduleType.none.value:
                text += f"    定时: {_get_schedule_label(msg.schedule_type, msg.interval_minutes)}\n"
            text += "\n"
    else:
        text += "暂无定时消息"

    from bot.keyboards.scheduled import scheduled_list_keyboard
    await q.edit_message_text(text, reply_markup=scheduled_list_keyboard(messages, target_chat_id))


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

        # 清除旧状态（避免状态冲突）
        await clear_user_state(session, chat_id=user.id, user_id=user.id)

        # 设置状态：等待输入配置
        # 注意：使用 user.id (私聊ID) 而不是 target_chat_id 来保存状态
        # 这样在私聊中发送消息时能正确读取状态
        await set_user_state(
            session,
            chat_id=user.id,  # 使用私聊ID保存状态
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
    text += "是否重复: 是\n"
    text += "```\n\n"
    text += "参数说明：\n"
    text += "• 消息内容：要发送的文本内容\n"
    text += "• 定时类型：指定发送间隔类型\n"
    text += "• 初始延迟：首次发送前的延迟分钟数\n"
    text += "• 是否重复：是=重复发送，否=只发送一次\n\n"
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
    text += "是否重复: 是\n"
    text += "```"

    await q.edit_message_text(text)


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
    # 在函数最开始添加明显的日志，用于诊断处理器是否被调用
    import structlog
    log = structlog.get_logger(__name__)
    log.warning(
        "=== scheduled_message_handler CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or "")[:50] if update.effective_message else "",
    )

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
        # 获取用户状态
        # 注意：状态使用 chat_id=user.id (私聊ID) 保存，所以读取时也使用 user.id
        state = None
        state_data_dict = None
        if chat.type == "private":
            # 私聊模式：直接使用 user.id 查询状态
            state = await get_user_state(session, chat_id=user.id, user_id=user.id)

            # 添加调试日志
            log.info(
                "scheduled_message_handler_private",
                user_id=user.id,
                chat_id=user.id,
                state_type=state.state_type if state else None,
                text_preview=text[:50] if text else ""
            )

            if state is None:
                # 用户未开始定时消息创建流程，静默返回让其他处理器处理
                await session.commit()
                return

            # 验证状态中是否有目标群组ID
            target_chat_id = state.state_data.get("target_chat_id")
            if target_chat_id is None:
                await update.effective_message.reply_text(
                    "❌ 状态数据不完整\n\n"
                    "请重新点击「创建定时消息」按钮开始"
                )
                await session.commit()
                return
        else:
            # 群聊模式：从当前群组获取状态
            state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

        # 只处理定时消息创建流程的状态
        if state is None or state.state_type != ConversationStateType.scheduled_create.value:
            # 静默返回，让其他处理器有机会处理
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
        repeat_enabled = False

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
                i += 1

        # 解析是否重复
        if i < len(lines):
            repeat_line = lines[i].strip()
            if repeat_line.startswith("是否重复:"):
                value = repeat_line.split(":", 1)[1].strip().lower()
                repeat_enabled = value in ["是", "yes", "true", "1"]

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
            repeat_enabled=repeat_enabled,
        )

        if not result.success:
            error_messages = {
                "invalid_content": "消息内容无效",
                "invalid_schedule_type": "定时类型无效",
                "invalid_interval": "间隔设置无效",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态
        # 注意：在私聊模式下，状态使用 user.id 保存，所以清除时也使用 user.id
        # 在群聊模式下，状态使用 target_chat_id 保存
        if update.effective_chat.type == "private":
            await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        else:
            await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        # 转换时间为北京时间（UTC+8）
        beijing_time = result.message.next_send_time + dt.timedelta(hours=8)

        reply_text = f"✅ 定时消息创建成功！\n\n"
        reply_text += f"📝 内容: {content[:50]}{'...' if len(content) > 50 else ''}\n"
        reply_text += f"⏰ 间隔: {_get_schedule_label(schedule_type, None)}\n"
        reply_text += f"🔄 重复: {'是' if repeat_enabled else '否'}\n"
        reply_text += f"🕐 首次发送: {beijing_time.strftime('%Y-%m-%d %H:%M:%S')}(北京时间)\n"
        reply_text += f"\n消息ID: {result.message.id}"

        # 只显示一个返回按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« 返回管理菜单", callback_data=f"adm:menu:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

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
