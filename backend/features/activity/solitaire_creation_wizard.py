from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.activity.services.solitaire_service import create_solitaire, format_solitaire_message
from backend.features.activity.solitaire_shared import (
    WAIT_DEADLINE,
    WAIT_DESCRIPTION,
    WAIT_MAX_PARTICIPANTS,
    WAIT_POINTS_REQUIRED,
)
from backend.features.activity.ui.solitaire import solitaire_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.time_helper import LOCAL_TIMEZONE
from backend.shared.time_ui import build_copy_time_keyboard, build_datetime_prompt_text, next_top_of_hour


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
    deadline_sample_text = next_top_of_hour(days_offset=1).astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    await update.effective_message.reply_text(
        build_datetime_prompt_text(
            title="🧩 接龙 | 截止时间",
            sample_time_text=deadline_sample_text,
            input_hint="👉 请输入截止时间，或输入 /skip 跳过：",
            extra_tips=[
                f"积分限制: {points_required or '无限制'}",
                "不设置则一直有效，直到手动结束。",
            ],
        ),
        parse_mode="HTML",
        reply_markup=build_copy_time_keyboard(None, deadline_sample_text),
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
