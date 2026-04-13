from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.activity.services.solitaire_service import (
    create_solitaire,
    format_solitaire_message,
    parse_config_value as _parse_config_value,
)
from backend.features.activity.solitaire_shared import (
    WAIT_CONFIG,
    WAIT_DEADLINE,
    WAIT_DESCRIPTION,
    WAIT_MAX_PARTICIPANTS,
    WAIT_POINTS_REQUIRED,
)
from backend.features.activity.ui.solitaire import get_join_solitaire_keyboard, solitaire_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.chat_context import PrivateChatContext


async def solitaire_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", {"target_chat_id": target_chat_id})
        await session.commit()

    now_local = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))
    deadline_example = now_local + dt.timedelta(hours=24)
    text = (
        "➕ 创建接龙 ( /cancel 取消)\n\n"
        "请按以下格式一次性发送配置：\n\n"
        "```\n"
        "接龙标题\n"
        "描述（可选，可直接留空）\n"
        "最大人数: 0（0=无限制）\n"
        "参与积分: 0（0=无限制）\n"
        "截止时间: YYYY-MM-DD HH:MM（可选，可直接留空）\n"
        "```\n\n"
        "示例:\n"
        "```\n"
        "今晚聚餐\n"
        "一起吃火锅\n"
        "最大人数: 10\n"
        "参与积分: 50\n"
        f"截止时间: {deadline_example.strftime('%Y-%m-%d %H:%M')}\n"
        "```"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"solitaire:cancel:{target_chat_id}")]]
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return WAIT_CONFIG


async def solitaire_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        if not state or not state.state_data.get("target_chat_id"):
            await update.effective_message.reply_text("会话已过期，请重新开始")
            return ConversationHandler.END
        target_chat_id = state.state_data["target_chat_id"]

    try:
        lines = update.effective_message.text.strip().split("\n")
        title = lines[0].strip() if lines else ""
        description = None
        max_participants = None
        points_required = None
        deadline = None

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("最大人数:") or line.startswith("最大人数："):
                try:
                    value = _parse_config_value(line, "最大人数")
                    if value:
                        max_participants = int(value)
                        if max_participants <= 0:
                            max_participants = None
                except ValueError:
                    pass
            elif line.startswith("参与积分:") or line.startswith("参与积分："):
                try:
                    value = _parse_config_value(line, "参与积分")
                    if value:
                        points_required = int(value)
                        if points_required < 0:
                            points_required = None
                except ValueError:
                    pass
            elif line.startswith("截止时间:") or line.startswith("截止时间："):
                try:
                    value = _parse_config_value(line, "截止时间")
                    if value:
                        deadline_local = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
                        local_tz = dt.timezone(dt.timedelta(hours=8))
                        deadline = deadline_local.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)
                except ValueError:
                    pass
            elif not description:
                description = line

        if not title:
            await update.effective_message.reply_text("❌ 标题不能为空\n\n请重新输入配置")
            return WAIT_CONFIG

        if deadline and deadline <= dt.datetime.now(dt.timezone.utc):
            await update.effective_message.reply_text("❌ 截止时间必须是未来时间\n\n请重新输入配置")
            return WAIT_CONFIG

        async with db.session_factory() as session:
            result = await create_solitaire(
                session,
                chat_id=target_chat_id,
                created_by_user_id=user.id,
                title=title,
                description=description,
                max_participants=max_participants,
                points_required=points_required,
                deadline=deadline,
            )
            if result.success:
                text_msg = format_solitaire_message(result.entity)
                try:
                    keyboard = get_join_solitaire_keyboard(result.entity.id)
                    group_message = await context.bot.send_message(
                        chat_id=target_chat_id,
                        text=text_msg,
                        reply_markup=keyboard,
                    )
                    result.entity.message_id = group_message.message_id
                    await session.commit()
                except Exception:
                    pass

                keyboard = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔙 返回接龙管理", callback_data=f"solitaire:menu:{target_chat_id}")],
                        [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:{target_chat_id}")],
                    ]
                )
                await update.effective_message.reply_text(
                    f"✅ 接龙创建成功！\n\n已发送到群组\n\n接龙ID: {result.entity.id}",
                    reply_markup=keyboard,
                )
                await clear_user_state(session, chat.id, user.id)
                await session.commit()
            else:
                await update.effective_message.reply_text(f"❌ 创建失败: {result.error or '未知错误'}")
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 配置格式错误，请检查后重试\n\n错误: {str(exc)}")
        return WAIT_CONFIG

    return ConversationHandler.END


async def solitaire_create_title_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    user = update.effective_user
    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_data = await set_user_state(session, chat.id, user.id, "solitaire_create", {"title": update.effective_message.text})
        await session.commit()
    await update.effective_message.reply_text(
        f"标题: {state_data.state_data.get('title')}\n\n请输入接龙描述（可选）\n\n输入 /skip 跳过"
    )
    return WAIT_DESCRIPTION


async def solitaire_create_description_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
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
            deadline = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")
            if deadline.tzinfo is None:
                local_tz = dt.timezone(dt.timedelta(hours=8))
                deadline = deadline.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)
        except ValueError:
            await update.effective_message.reply_text("时间格式错误，请使用 YYYY-MM-DD HH:MM 格式或 /skip 跳过")
            return WAIT_DEADLINE

    state_data["deadline"] = deadline
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
            message = await update.effective_message.reply_text(
                format_solitaire_message(result.entity),
                reply_markup=solitaire_menu_keyboard(),
            )
            result.entity.message_id = message.message_id
            await session.commit()
        else:
            await update.effective_message.reply_text("❌ 创建失败", reply_markup=solitaire_menu_keyboard())
    return ConversationHandler.END


async def solitaire_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    parts = (q.data or "").split(":")
    if len(parts) >= 3:
        try:
            target_chat_id = int(parts[2])
        except ValueError:
            target_chat_id = None
    else:
        target_chat_id = None

    if target_chat_id is None:
        if chat.type == "private":
            from backend.shared.handlers.base.chat_resolver import ChatResolver

            db: Database = context.application.bot_data["db"]
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)
        else:
            target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await clear_user_state(session, target_chat_id, user.id)
        await session.commit()

    if chat.type == "private":
        from backend.features.admin.admin_handler import _show_private_admin_menu

        await _show_private_admin_menu(update, context, target_chat_id)
    else:
        await q.edit_message_text("已取消创建", reply_markup=solitaire_menu_keyboard(None))
    return ConversationHandler.END
