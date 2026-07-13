from __future__ import annotations

import asyncio
from dataclasses import dataclass
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.config.core.settings import get_settings
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.handlers.base.state_helper import StateHelper
from backend.shared.ui.common.chat_group import chat_group_list_keyboard
from backend.shared.ui.common.start import create_start_guide_keyboard
from backend.features.group_ops.services.chat_group_service import (
    format_empty_chat_list_hint,
    format_group_guide_message,
    format_private_chat_current_title,
    format_private_chat_list,
    format_private_chat_welcome,
    get_user_current_chat,
    get_user_managed_chats,
    set_user_current_chat,
)
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.platform.state.conversation_state_service import SELECTED_CHAT_STATE
from backend.platform.state.state_service import clear_private_input_state, clear_user_state, get_user_state, set_user_state
from backend.shared.async_tasks import spawn_background_task
from backend.shared.services.user_service import ensure_user
from backend.features.group_ops.start_payloads import (
    extract_start_payload as _extract_start_payload,
    handle_car_review_submit_start as _handle_car_review_submit_start,
    handle_invite_relay_start as _handle_invite_relay_start,
    handle_teacher_location_start as _handle_teacher_location_start,
    handle_teacher_self_location_start as _handle_teacher_self_location_start,
)


log = structlog.get_logger(__name__)


async def _list_teacher_self_chats(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    from backend.features.garage.services.garage_features_service import GarageAuthService

    db: Database = context.application.bot_data["db"]
    try:
        async with db.session_factory() as session:
            rows = await GarageAuthService.list_teacher_self_service_chats(session, user_id)
            await session.commit()
        return rows
    except Exception as exc:
        log.warning("teacher_self_home_extension_failed", user_id=user_id, error=str(exc))
        return []


async def _build_private_home_markup(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    chats: list[tuple[int, str, bool]],
    current_chat_id: int | None,
) -> InlineKeyboardMarkup | None:
    teacher_rows = await _list_teacher_self_chats(context, user_id)
    if not chats and not teacher_rows:
        return chat_group_list_keyboard(chats, current_chat_id)

    rows: list[list[InlineKeyboardButton]] = []
    if chats:
        rows.extend(chat_group_list_keyboard(chats, current_chat_id).inline_keyboard)
    if teacher_rows:
        rows.append([InlineKeyboardButton("👩‍🏫 老师资料维护", callback_data="teacher:self:list")])
    return InlineKeyboardMarkup(rows) if rows else None


async def _send_guide_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat, *, user) -> None:
    """发送群组引导消息（共享逻辑）

    Args:
        update: Telegram 更新对象
        context: Bot 上下文
        chat: 群组聊天对象
        user: 用户对象
    """
    db: Database = context.application.bot_data["db"]

    # 设置当前管理的群组
    await set_user_current_chat(db, user.id, chat.id)

    # 获取配置的删除时间
    app_settings = get_settings()
    delete_delay = app_settings.group_guide_message_delete_seconds

    # 使用 keyboards 层创建键盘
    keyboard = create_start_guide_keyboard(context.bot.username)

    # 使用 service 层格式化消息
    text = format_group_guide_message(bot_username=context.bot.username)

    # 发送引导消息（使用 send_message 而不是 reply_text，因为消息会被删除）
    try:
        msg = await context.bot.send_message(
            chat_id=chat.id,
            text=text,
            reply_markup=keyboard
        )
    except Exception as exc:
        log.warning("start_guide_send_failed", chat_id=chat.id, error=str(exc))
        return

    # 删除用户发送的消息
    try:
        await update.effective_message.delete()
    except Exception as e:
        log.warning("delete_user_message_failed", error=str(e))

    # 延迟后删除机器人消息（保持群组整洁）
    async def delete_later():
        try:
            await asyncio.sleep(delete_delay)
            await msg.delete()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("delete_bot_message_failed", error=str(e))

    spawn_background_task(context, delete_later(), name="start_handler.delete_guide_message")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """上下文感知的 /start：根据用户状态返回不同内容"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type != "private":
        allowed = await ensure_command_enabled(context, update, command_key="start")
        if not allowed:
            return
    if chat.type == "private":
        await _handle_private_start(update, context)
        return
    await _handle_group_start(update, context)


async def _handle_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payload = _extract_start_payload(update.effective_message.text)
    payload_handlers = (
        _handle_invite_relay_start,
        _handle_teacher_location_start,
        _handle_teacher_self_location_start,
        _handle_car_review_submit_start,
    )
    for handler in payload_handlers:
        if payload and await handler(update, context, payload):
            return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    chats = await get_user_managed_chats(db, user_id, context.bot)
    current_chat_id = await get_user_current_chat(db, user_id)
    reply_markup = await _build_private_home_markup(
        context,
        user_id=user_id,
        chats=chats,
        current_chat_id=current_chat_id,
    )
    teacher_rows = await _list_teacher_self_chats(context, user_id)
    text = _private_start_text(
        chats,
        current_chat_id=current_chat_id,
        bot_username=context.bot.username,
        has_teacher_rows=bool(teacher_rows),
    )
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


def _private_start_text(
    chats: list[tuple[int, str, bool]],
    *,
    current_chat_id: int | None,
    bot_username: str,
    has_teacher_rows: bool,
) -> str:
    if not chats:
        text = format_private_chat_welcome(bot_username, has_chats=False)
        suffix = "\n\n如果你是认证老师，也可以点下面按钮维护老师资料。"
        return text + (suffix if has_teacher_rows else "")
    current_title = next((title for chat_id, title, _ in chats if chat_id == current_chat_id), None)
    text = (
        format_private_chat_current_title(current_title)
        if current_title
        else format_private_chat_list(len(chats))
    )
    suffix = "\n\n认证老师也可以用下面按钮维护自己的资料。"
    return text + (suffix if has_teacher_rows else "")


async def _handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

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
        await get_chat_settings(session, chat.id)

        # 检查用户是否有对话状态
        state = await StateHelper.get_state_by_chat(session, chat, user.id)

        # 如果有状态，清除状态
        if state is not None:
            await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    await _send_guide_message(update, context, chat, user=user)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消当前流程，返回相应界面

    支持私聊和群聊两种场景：
    - 私聊：清除目标群组的配置状态，返回管理菜单
    - 群聊：清除当前群组的状态，发送引导消息
    """
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    target_chat_id = await get_user_current_chat(db, user.id)
    async with db.session_factory() as session:
        targets = await _clear_cancel_state(
            session,
            chat=chat,
            user_id=user.id,
            target_chat_id=target_chat_id,
        )
        await session.commit()
    await _show_cancel_result(update, context, targets=targets)


@dataclass(frozen=True, slots=True)
class _CancelTargets:
    target_chat_id: int | None
    teacher_self_chat_id: int | None
    private: bool


def _targets_from_private_state(state, current_chat_id: int | None) -> _CancelTargets:
    if state is None or not isinstance(state.state_data, dict):
        return _CancelTargets(current_chat_id, None, True)
    data = state.state_data
    restored = data.get("previous_selected_chat_id")
    should_restore = (
        state.state_type == ConversationStateType.teacher_search_member_location_input.value
        and isinstance(restored, int)
    )
    target_chat_id = restored if should_restore else current_chat_id
    teacher_states = {
        ConversationStateType.teacher_self_location_input.value,
        ConversationStateType.teacher_self_region_input.value,
        ConversationStateType.teacher_self_price_input.value,
        ConversationStateType.teacher_self_labels_input.value,
    }
    teacher_target = data.get("target_chat_id")
    teacher_chat_id = (
        teacher_target
        if state.state_type in teacher_states and isinstance(teacher_target, int)
        else None
    )
    return _CancelTargets(target_chat_id, teacher_chat_id, True)


async def _clear_cancel_state(
    session,
    *,
    chat,
    user_id: int,
    target_chat_id: int | None,
) -> _CancelTargets:
    if chat.type != "private":
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await clear_user_state(session, chat_id=chat.id, user_id=user_id)
        return _CancelTargets(chat.id, None, False)
    private_state = await get_user_state(session, chat_id=user_id, user_id=user_id)
    targets = _targets_from_private_state(private_state, target_chat_id)
    await clear_private_input_state(session, user_id)
    if targets.target_chat_id != target_chat_id:
        await set_user_state(
            session,
            chat_id=user_id,
            user_id=user_id,
            state_type=SELECTED_CHAT_STATE,
            state_data={"managed_chat_id": targets.target_chat_id},
        )
    if targets.target_chat_id:
        await clear_user_state(session, chat_id=targets.target_chat_id, user_id=user_id)
    return targets


async def _show_cancel_result(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    targets: _CancelTargets,
) -> None:
    if not targets.private:
        await _send_guide_message(update, context, update.effective_chat, user=update.effective_user)
        return
    if targets.teacher_self_chat_id is not None:
        from backend.features.admin.garage.teacher_self import show_teacher_self_home

        await show_teacher_self_home(update, context, targets.teacher_self_chat_id)
        return
    if targets.target_chat_id:
        from backend.features.admin.admin_handler import _show_private_admin_menu

        await _show_private_admin_menu(update, context, targets.target_chat_id)
        return
    db: Database = context.application.bot_data["db"]
    chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
    reply_markup = await _build_private_home_markup(
        context,
        user_id=update.effective_user.id,
        chats=chats,
        current_chat_id=None,
    )
    await update.effective_message.reply_text("已取消当前配置", reply_markup=reply_markup)


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
        state = await StateHelper.get_state_by_chat(session, chat, user.id)
        await session.commit()

    # selected_chat 只是当前群组选择，不是输入流程状态。
    if state is not None and state.state_type != "selected_chat":
        return

    # 没有对话状态，显示群组列表
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await get_user_current_chat(db, user.id)
    reply_markup = await _build_private_home_markup(
        context,
        user_id=user.id,
        chats=chats,
        current_chat_id=current_chat_id,
    )
    teacher_self_rows = await _list_teacher_self_chats(context, user.id)

    if not chats:
        # 使用 service 层格式化消息
        text = format_empty_chat_list_hint()
        if teacher_self_rows:
            text += "\n\n如果你是认证老师，也可以点下面按钮维护老师资料。"
        await update.effective_message.reply_text(
            text,
            reply_markup=reply_markup,
        )
    else:
        # 使用 service 层格式化消息
        text = format_private_chat_list(len(chats))
        if teacher_self_rows:
            text += "\n\n认证老师也可以用下面按钮维护自己的资料。"
        await update.effective_message.reply_text(
            text,
            reply_markup=reply_markup,
        )
