from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.activity.services.solitaire_service import (
    create_solitaire,
    format_solitaire_message,
    parse_config_value as _parse_config_value,
)
from backend.features.activity.solitaire_shared import WAIT_CONFIG
from backend.features.activity.ui.solitaire import get_join_solitaire_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state


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
        parsed = _parse_solitaire_config(update.effective_message.text)
        if not parsed["title"]:
            await update.effective_message.reply_text("❌ 标题不能为空\n\n请重新输入配置")
            return WAIT_CONFIG

        deadline = parsed["deadline"]
        if deadline and deadline <= dt.datetime.now(dt.timezone.utc):
            await update.effective_message.reply_text("❌ 截止时间必须是未来时间\n\n请重新输入配置")
            return WAIT_CONFIG

        async with db.session_factory() as session:
            result = await create_solitaire(
                session,
                chat_id=target_chat_id,
                created_by_user_id=user.id,
                title=parsed["title"],
                description=parsed["description"],
                max_participants=parsed["max_participants"],
                points_required=parsed["points_required"],
                deadline=deadline,
            )
            if result.success:
                await _publish_created_solitaire(update, context, session, result, target_chat_id, chat.id, user.id)
            else:
                await update.effective_message.reply_text(f"❌ 创建失败: {result.error or '未知错误'}")
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 配置格式错误，请检查后重试\n\n错误: {str(exc)}")
        return WAIT_CONFIG

    return ConversationHandler.END


def _parse_solitaire_config(raw_text: str) -> dict[str, object]:
    lines = raw_text.strip().split("\n")
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

    return {
        "title": title,
        "description": description,
        "max_participants": max_participants,
        "points_required": points_required,
        "deadline": deadline,
    }


async def _publish_created_solitaire(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    result,
    target_chat_id: int,
    state_chat_id: int,
    user_id: int,
) -> None:
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
            [InlineKeyboardButton("🔙 返回接龙管理", callback_data=f"adm:menu:solitaire:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
        ]
    )
    await update.effective_message.reply_text(
        f"✅ 接龙创建成功！\n\n已发送到群组\n\n接龙ID: {result.entity.id}",
        reply_markup=keyboard,
    )
    await clear_user_state(session, state_chat_id, user_id)
    await session.commit()
