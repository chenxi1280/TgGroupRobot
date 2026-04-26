from __future__ import annotations

import asyncio
import datetime as dt
import structlog
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from backend.platform.config.core.settings import get_settings
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import InviteLink
from backend.platform.db.schema.models.enums import ConversationStateType, InviteLinkStatus
from backend.shared.handlers.base.state_helper import StateHelper
from backend.shared.i18n.strings import t
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


log = structlog.get_logger(__name__)


def _extract_start_payload(text: str | None) -> str:
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


async def _handle_invite_relay_start(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("inv_"):
        return False
    try:
        link_id = int(payload.removeprefix("inv_"))
    except ValueError:
        await update.effective_message.reply_text("邀请链接无效，请重新获取。")
        return True

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await session.execute(select(InviteLink).where(InviteLink.id == link_id))
        link = result.scalar_one_or_none()
        await session.commit()

    now = dt.datetime.now(dt.UTC)
    if (
        link is None
        or link.status != InviteLinkStatus.active.value
        or (link.expire_date is not None and link.expire_date < now)
    ):
        await update.effective_message.reply_text("邀请链接已失效，请重新获取。")
        return True

    user_id = update.effective_user.id
    user_data = getattr(context, "user_data", None)
    if isinstance(user_data, dict):
        user_data["pending_invite_link_id"] = link.id

    from backend.features.verification.verification_join_guards import cache_invite_join_hint

    cache_invite_join_hint(context, chat_id=link.chat_id, user_id=user_id, invite_link=link.invite_link)
    await update.effective_message.reply_text(
        "🔗 邀请链接已准备好\n\n点击下方按钮进入群组，审核通过后会自动计入邀请统计。",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("进入群组", url=link.invite_link)],
        ]),
    )
    return True


async def _handle_teacher_location_start(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("tloc_"):
        return False
    try:
        target_chat_id = int(payload.removeprefix("tloc_"))
    except ValueError:
        await update.effective_message.reply_text("定位入口无效，请回群重新点击“私聊更新定位”。")
        return True

    from backend.platform.db.schema.models.core import TgChat
    from backend.platform.db.schema.models.garage_features import TeacherSearchSetting

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat = await session.get(TgChat, target_chat_id)
        setting = await session.get(TeacherSearchSetting, target_chat_id) if target_chat is not None else None
        if target_chat is None:
            await session.commit()
            await update.effective_message.reply_text("定位入口已失效，请回群重新点击“私聊更新定位”。")
            return True
        if setting is None or not setting.nearby_search_enabled:
            await session.commit()
            await update.effective_message.reply_text("该群暂未启用附近搜索。")
            return True
        existing_private_state = await get_user_state(
            session,
            chat_id=update.effective_user.id,
            user_id=update.effective_user.id,
        )
        state_data = {"target_chat_id": target_chat_id}
        if (
            existing_private_state is not None
            and existing_private_state.state_type == SELECTED_CHAT_STATE
            and isinstance(existing_private_state.state_data, dict)
            and isinstance(existing_private_state.state_data.get("managed_chat_id"), int)
        ):
            state_data["previous_selected_chat_id"] = existing_private_state.state_data["managed_chat_id"]
        await set_user_state(
            session,
            chat_id=update.effective_user.id,
            user_id=update.effective_user.id,
            state_type=ConversationStateType.teacher_search_member_location_input.value,
            state_data=state_data,
        )
        await session.commit()

    title = target_chat.title or str(target_chat_id)
    await update.effective_message.reply_text(
        (
            "📍 更新附近搜索定位\n\n"
            f"目标群：{title}\n\n"
            "请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。\n"
            "定位只用于附近老师搜索，不会在群里公开。"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


async def _handle_teacher_self_location_start(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("tselfloc_"):
        return False
    try:
        target_chat_id = int(payload.removeprefix("tselfloc_"))
    except ValueError:
        await update.effective_message.reply_text("老师定位入口无效，请回群重新点击。")
        return True

    from backend.features.garage.services.garage_features_service import GarageAuthService
    from backend.platform.db.schema.models.core import TgChat

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat = await session.get(TgChat, target_chat_id)
        if target_chat is None:
            await session.commit()
            await update.effective_message.reply_text("老师定位入口已失效，请回群重新点击。")
            return True
        if not await GarageAuthService.is_effective_certified_teacher(
            session,
            target_chat_id,
            update.effective_user.id,
        ):
            await session.commit()
            await update.effective_message.reply_text("你不是该群的认证老师，无法更新老师服务定位。")
            return True
        await set_user_state(
            session,
            chat_id=update.effective_user.id,
            user_id=update.effective_user.id,
            state_type=ConversationStateType.teacher_self_location_input.value,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    title = target_chat.title or str(target_chat_id)
    await update.effective_message.reply_text(
        (
            "📍 更新老师服务定位\n\n"
            f"目标群：{title}\n\n"
            "请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。\n"
            "该定位用于老师附近搜索，不会覆盖你的群友附近查询定位。"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


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


async def _send_guide_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat, user) -> None:
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
    msg = await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        reply_markup=keyboard
    )

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

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        allowed = await ensure_command_enabled(context, update, command_key="start")
        if not allowed:
            return

    if chat.type == "private":
        payload = _extract_start_payload(update.effective_message.text)
        if payload and await _handle_invite_relay_start(update, context, payload):
            return
        if payload and await _handle_teacher_location_start(update, context, payload):
            return
        if payload and await _handle_teacher_self_location_start(update, context, payload):
            return

        # 私聊中显示群组列表
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
            text = format_private_chat_welcome(context.bot.username, has_chats=False)
            if teacher_self_rows:
                text += "\n\n如果你是认证老师，也可以点下面按钮维护老师资料。"
            await update.effective_message.reply_text(
                text,
                reply_markup=reply_markup,
            )
        else:
            # 有当前选中的群组，显示该群组信息
            if current_chat_id:
                for cid, title, _ in chats:
                    if cid == current_chat_id:
                        # 使用 service 层格式化消息
                        text = format_private_chat_current_title(title)
                        if teacher_self_rows:
                            text += "\n\n认证老师也可以用下面按钮维护自己的资料。"
                        await update.effective_message.reply_text(
                            text,
                            reply_markup=reply_markup,
                        )
                        return

            # 没有选中群组，显示列表
            text = format_private_chat_list(len(chats))
            if teacher_self_rows:
                text += "\n\n认证老师也可以用下面按钮维护自己的资料。"
            await update.effective_message.reply_text(
                text,
                reply_markup=reply_markup,
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
        state = await StateHelper.get_state_by_chat(session, chat, user.id)

        # 如果有状态，清除状态
        if state is not None:
            await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 发送引导消息
    await _send_guide_message(update, context, chat, user)


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

    # 获取当前选中的群组
    target_chat_id = await get_user_current_chat(db, user.id)

    async with db.session_factory() as session:
        if chat.type == "private":
            private_state = await get_user_state(session, chat_id=user.id, user_id=user.id)
            restored_chat_id = None
            teacher_self_target_chat_id = None
            if (
                private_state is not None
                and private_state.state_type == ConversationStateType.teacher_search_member_location_input.value
                and isinstance(private_state.state_data, dict)
                and isinstance(private_state.state_data.get("previous_selected_chat_id"), int)
            ):
                restored_chat_id = private_state.state_data["previous_selected_chat_id"]
            if (
                private_state is not None
                and private_state.state_type in {
                    ConversationStateType.teacher_self_location_input.value,
                    ConversationStateType.teacher_self_region_input.value,
                    ConversationStateType.teacher_self_price_input.value,
                    ConversationStateType.teacher_self_labels_input.value,
                }
                and isinstance(private_state.state_data, dict)
                and isinstance(private_state.state_data.get("target_chat_id"), int)
            ):
                teacher_self_target_chat_id = private_state.state_data["target_chat_id"]
            await clear_private_input_state(session, user.id)
            if restored_chat_id is not None:
                await set_user_state(
                    session,
                    chat_id=user.id,
                    user_id=user.id,
                    state_type=SELECTED_CHAT_STATE,
                    state_data={"managed_chat_id": restored_chat_id},
                )
                target_chat_id = restored_chat_id
            # 私聊：清除目标群组的状态
            if target_chat_id:
                await clear_user_state(session, chat_id=target_chat_id, user_id=user.id)
        else:
            # 群聊：清除当前群组的状态
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await clear_user_state(session, chat_id=chat.id, user_id=user.id)
        await session.commit()

    # 返回相应界面
    if chat.type == "private":
        if teacher_self_target_chat_id is not None:
            from backend.features.admin.garage.teacher_self import show_teacher_self_home

            await show_teacher_self_home(update, context, teacher_self_target_chat_id)
            return
        if target_chat_id:
            # 返回该群组的管理菜单
            from backend.features.admin.admin_handler import _show_private_admin_menu
            await _show_private_admin_menu(update, context, target_chat_id)
        else:
            # 没有选中群组，返回群组列表
            chats = await get_user_managed_chats(db, user.id, context.bot)
            reply_markup = await _build_private_home_markup(
                context,
                user_id=user.id,
                chats=chats,
                current_chat_id=target_chat_id,
            )
            await update.effective_message.reply_text(
                "已取消当前配置",
                reply_markup=reply_markup,
            )
    else:
        # 群聊发送引导消息
        await _send_guide_message(update, context, chat, user)


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
