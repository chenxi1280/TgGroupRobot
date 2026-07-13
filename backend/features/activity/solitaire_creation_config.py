from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import structlog
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

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _SolitaireConfigValues:
    title: str
    description: str | None = None
    max_participants: int | None = None
    points_required: int | None = None
    deadline: dt.datetime | None = None


async def _load_solitaire_target(update, session, chat_id: int, *, user_id: int) -> int | None:
    state = await get_user_state(session, chat_id, user_id)
    target_chat_id = state.state_data.get("target_chat_id") if state else None
    if target_chat_id:
        return target_chat_id
    await update.effective_message.reply_text("会话已过期，请重新开始")
    return None


async def _validate_solitaire_creation_input(message) -> dict[str, object] | None:
    parsed = _parse_solitaire_config(message.text)
    if not parsed["title"]:
        await message.reply_text("❌ 标题不能为空\n\n请重新输入配置")
        return None
    deadline = parsed["deadline"]
    if deadline and deadline <= dt.datetime.now(dt.timezone.utc):
        await message.reply_text("❌ 截止时间必须是未来时间\n\n请重新输入配置")
        return None
    return parsed


async def _create_configured_solitaire(update, context, db, *, parsed, target_chat_id: int, state_chat_id: int, user_id: int) -> bool:
    async with db.session_factory() as session:
        result = await create_solitaire(
            session,
            chat_id=target_chat_id,
            created_by_user_id=user_id,
            title=parsed["title"],
            description=parsed["description"],
            max_participants=parsed["max_participants"],
            points_required=parsed["points_required"],
            deadline=parsed["deadline"],
        )
        if not result.success:
            await update.effective_message.reply_text("❌ 创建失败，请稍后重试。")
            return True
        published = await _publish_created_solitaire(
            update, context, session, result=result, target_chat_id=target_chat_id, state_chat_id=state_chat_id, user_id=user_id
        )
        if published:
            return True
        await update.effective_message.reply_text("❌ 接龙创建失败，请检查机器人在目标群的发言权限后重试。")
        return False


async def solitaire_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat_id = await _load_solitaire_target(update, session, chat.id, user_id=user.id)
    if target_chat_id is None:
        return ConversationHandler.END

    try:
        parsed = await _validate_solitaire_creation_input(update.effective_message)
        if parsed is None:
            return WAIT_CONFIG
        completed = await _create_configured_solitaire(
            update, context, db, parsed=parsed, target_chat_id=target_chat_id, state_chat_id=chat.id, user_id=user.id
        )
        return ConversationHandler.END if completed else WAIT_CONFIG
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 配置格式错误，请检查后重试\n\n错误: {str(exc)}")
        return WAIT_CONFIG

    return ConversationHandler.END


def _parse_int_config(line: str, label: str, *, minimum: int) -> int | None:
    try:
        value = _parse_config_value(line, label)
        number = int(value) if value else None
    except ValueError:
        return None
    return number if number is not None and number >= minimum else None


def _parse_deadline_config(line: str) -> dt.datetime | None:
    try:
        value = _parse_config_value(line, "截止时间")
        if not value:
            return None
        local_time = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    local_tz = dt.timezone(dt.timedelta(hours=8))
    return local_time.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)


def _apply_solitaire_config_line(config: _SolitaireConfigValues, line: str) -> _SolitaireConfigValues:
    if line.startswith(("最大人数:", "最大人数：")):
        return replace(config, max_participants=_parse_int_config(line, "最大人数", minimum=1))
    if line.startswith(("参与积分:", "参与积分：")):
        return replace(config, points_required=_parse_int_config(line, "参与积分", minimum=0))
    if line.startswith(("截止时间:", "截止时间：")):
        return replace(config, deadline=_parse_deadline_config(line))
    if config.description is None:
        return replace(config, description=line)
    return config


def _parse_solitaire_config(raw_text: str) -> dict[str, object]:
    lines = raw_text.strip().split("\n")
    config = _SolitaireConfigValues(title=lines[0].strip() if lines else "")
    for line in lines[1:]:
        line = line.strip()
        if line:
            config = _apply_solitaire_config_line(config, line)
    return {
        "title": config.title,
        "description": config.description,
        "max_participants": config.max_participants,
        "points_required": config.points_required,
        "deadline": config.deadline,
    }


async def _publish_created_solitaire(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, result,
    target_chat_id: int,
    state_chat_id: int,
    user_id: int,
) -> bool:
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
    except Exception as exc:
        await session.rollback()
        log.warning(
            "solitaire_publish_failed",
            solitaire_id=result.entity.id,
            target_chat_id=target_chat_id,
            state_chat_id=state_chat_id,
            user_id=user_id,
            error=str(exc),
        )
        return False

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
    return True
