from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.db.session import Database
from bot.keyboards.solitaire import (
    solitaire_create_keyboard,
    solitaire_detail_keyboard,
    solitaire_list_keyboard,
    solitaire_menu_keyboard,
)
from bot.models.enums import SolitaireStatus
from bot.services.chat_service import get_chat_settings
from bot.services.solitaire_service import (
    close_solitaire,
    create_solitaire,
    delete_solitaire,
    format_solitaire_message,
    get_chat_solitaires,
    get_solitaire,
    get_solitaire_stats,
    join_solitaire,
    update_entry,
)
from bot.services.state_service import clear_user_state, set_user_state, get_user_state
from bot.services.telegram_perm import is_user_admin

# 创建流程状态
WAIT_TITLE = 1
WAIT_DESCRIPTION = 2
WAIT_MAX_PARTICIPANTS = 3
WAIT_POINTS_REQUIRED = 4
WAIT_DEADLINE = 5

log = structlog.get_logger(__name__)


async def solitaire_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
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
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await session.commit()

    await q.edit_message_text(
        f"📋 [{chat.title}] 接龙管理\n\n管理群内接龙活动",
        reply_markup=solitaire_menu_keyboard(),
    )


async def solitaire_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    data = q.data or ""
    parts = data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaires = await get_chat_solitaires(session, target_chat_id)
        await session.commit()

    if not solitaires:
        keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
        await q.edit_message_text(
            "📋 接龙列表\n\n暂无接龙，点击「创建接龙」开始",
            reply_markup=keyboard,
        )
        return

    text = f"📋 接龙列表\n\n共 {len(solitaires)} 个接龙"
    keyboard = solitaire_list_keyboard(
        solitaires,
        target_chat_id if chat.type == "private" else None,
        page
    )
    await q.edit_message_text(text, reply_markup=keyboard)


async def solitaire_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙统计回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        stats = await get_solitaire_stats(session, target_chat_id)
        await session.commit()

    text = f"📊 接龙统计\n\n"
    text += f"总接龙数: {stats['total']}\n"
    text += f"进行中: {stats['active']}\n"
    text += f"已结束: {stats['closed']}\n"
    text += f"总参与人次: {stats['total_entries']}"

    keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
    await q.edit_message_text(text, reply_markup=keyboard)


async def solitaire_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙详情回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    solitaire_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await session.commit()
            await q.edit_message_text("接龙不存在", reply_markup=solitaire_menu_keyboard())
            return

        text = format_solitaire_message(solitaire, show_closed=False)
        is_active = solitaire.status == SolitaireStatus.active.value
        await session.commit()

    await q.edit_message_text(text, reply_markup=solitaire_detail_keyboard(solitaire_id, is_active))


async def solitaire_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", {})
        await session.commit()

    await q.edit_message_text(
        "➕ 创建接龙\n\n请输入接龙标题",
    )
    return WAIT_TITLE


async def solitaire_create_title_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理标题输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    title = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_data = await set_user_state(session, chat.id, user.id, "solitaire_create", {"title": title})
        await session.commit()

    await update.effective_message.reply_text(
        f"标题: {state_data.state_data.get('title')}\n\n请输入接龙描述（可选）\n\n输入 /skip 跳过"
    )
    return WAIT_DESCRIPTION


async def solitaire_create_description_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理描述输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        description = None if text == "/skip" else text
        state_data["description"] = description
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"描述: {description or '无'}\n\n请输入最大参与人数（可选）\n输入数字或 /skip 跳过"
    )
    return WAIT_MAX_PARTICIPANTS


async def solitaire_create_max_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理最大人数输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    max_participants = None
    if text != "/skip":
        try:
            max_participants = int(text)
            if max_participants <= 0:
                await update.effective_message.reply_text("人数必须大于0，请重新输入或 /skip 跳过")
                return WAIT_MAX_PARTICIPANTS
        except ValueError:
            await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
            return WAIT_MAX_PARTICIPANTS

    state_data["max_participants"] = max_participants

    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"最大人数: {max_participants or '无限制'}\n\n请输入参与所需积分（可选）\n输入数字或 /skip 跳过"
    )
    return WAIT_POINTS_REQUIRED


async def solitaire_create_points_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理积分限制输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    points_required = None
    if text != "/skip":
        try:
            points_required = int(text)
            if points_required < 0:
                await update.effective_message.reply_text("积分不能为负数，请重新输入或 /skip 跳过")
                return WAIT_POINTS_REQUIRED
        except ValueError:
            await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
            return WAIT_POINTS_REQUIRED

    state_data["points_required"] = points_required

    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"积分限制: {points_required or '无限制'}\n\n请输入截止时间（可选）\n格式: YYYY-MM-DD HH:MM 或 /skip 跳过\n示例: 2024-12-31 23:59"
    )
    return WAIT_DEADLINE


async def solitaire_create_deadline_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理截止时间输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    deadline = None
    if text != "/skip":
        try:
            import datetime as dt
            # 尝试解析时间格式
            deadline = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")
            # 转换为UTC
            import datetime as dt_module
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=dt_module.timezone.utc)
        except ValueError:
            await update.effective_message.reply_text("时间格式错误，请使用 YYYY-MM-DD HH:MM 格式或 /skip 跳过")
            return WAIT_DEADLINE

    state_data["deadline"] = deadline

    # 创建接龙
    async with db.session_factory() as session:
        result = await create_solitaire(
            session,
            chat_id=chat.id,
            created_by_user_id=user.id,
            title=state_data.get("title"),
            description=state_data.get("description"),
            max_participants=state_data.get("max_participants"),
            points_required=state_data.get("points_required"),
            deadline=state_data.get("deadline"),
        )

        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        if result.success:
            text_msg = format_solitaire_message(result.solitaire)
            message = await update.effective_message.reply_text(text_msg, reply_markup=solitaire_menu_keyboard())

            # 保存消息ID
            result.solitaire.message_id = message.message_id
            await session.commit()
        else:
            await update.effective_message.reply_text("❌ 创建失败", reply_markup=solitaire_menu_keyboard())

    return ConversationHandler.END


async def solitaire_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """取消创建流程"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
    else:
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await clear_user_state(session, target_chat_id, user.id)
        await session.commit()

    keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
    await q.edit_message_text("已取消创建", reply_markup=keyboard)
    return ConversationHandler.END


async def solitaire_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """刷新接龙详情"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    solitaire_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await session.commit()
            await q.edit_message_text("接龙不存在", reply_markup=solitaire_menu_keyboard())
            return

        text = format_solitaire_message(solitaire, show_closed=False)
        is_active = solitaire.status == SolitaireStatus.active.value
        await session.commit()

    await q.edit_message_text(text, reply_markup=solitaire_detail_keyboard(solitaire_id, is_active))


async def solitaire_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """结束接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    solitaire_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await close_solitaire(session, solitaire_id)
        await session.commit()

        if result.success:
            text = format_solitaire_message(result.solitaire, show_closed=False)
            await q.edit_message_text(text, reply_markup=solitaire_detail_keyboard(solitaire_id, False))
        else:
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "error": "结束失败",
            }.get(result.reason, "未知错误")
            keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
            await q.edit_message_text(f"❌ {reason_text}", reply_markup=keyboard)


async def solitaire_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    solitaire_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_solitaire(session, solitaire_id)
        await session.commit()

        keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
        if success:
            await q.edit_message_text("✅ 接龙已删除", reply_markup=keyboard)
        else:
            await q.edit_message_text("❌ 接龙不存在", reply_markup=keyboard)


async def solitaire_join_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理接龙参与消息（回复接龙消息）"""
    if update.effective_message is None or update.effective_chat is None or update.effective_user is None:
        return

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # 检查是否回复消息
    if not message.reply_to_message:
        return

    # 查找对应的接龙
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaires = await get_chat_solitaires(session, chat.id, active_only=True)

        target_solitaire = None
        for solitaire in solitaires:
            if solitaire.message_id == message.reply_to_message.message_id:
                target_solitaire = solitaire
                break

        if not target_solitaire:
            return  # 不是接龙消息

        # 检查是否已参与
        for entry in target_solitaire.entries:
            if entry.get("user_id") == user.id:
                # 已参与，更新内容
                result = await update_entry(session, target_solitaire.id, user.id, message.text)
                await session.commit()

                if result.success:
                    text = format_solitaire_message(result.solitaire)
                    await message.reply_to_message.edit_text(text)
                    await message.reply_text("✅ 已更新你的接龙内容")
                else:
                    await message.reply_text("❌ 更新失败")
                return

        # 新参与
        content = message.text
        username = user.username or user.full_name or f"用户{user.id}"

        result = await join_solitaire(session, target_solitaire.id, user.id, username, content)
        await session.commit()

        if result.success:
            text = format_solitaire_message(result.solitaire)
            await message.reply_to_message.edit_text(text)
            await message.reply_text("✅ 接龙成功！")
        else:
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "already_joined": "你已经参与了，请回复更新内容",
                "full": "接龙人数已满",
                "expired": "接龙已截止",
                "insufficient_points": "积分不足，无法参与",
                "error": "参与失败",
            }.get(result.reason, "未知错误")
            await message.reply_text(f"❌ {reason_text}")
