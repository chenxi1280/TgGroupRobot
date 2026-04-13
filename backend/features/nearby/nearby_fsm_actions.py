from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.nearby.services.nearby_profile_service import (
    clear_profile,
    get_or_create_profile,
    get_profile,
    update_profile,
)
from backend.features.nearby.ui.nearby import nearby_clear_confirm_keyboard, nearby_manage_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, set_user_state


async def handle_fsm_text_input_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    user = update.effective_user
    state_type = str(state.state_type)
    target_chat_id = int(state.state_data.get("target_chat_id", 0)) if state.state_data else 0
    if target_chat_id == 0:
        await update.effective_message.reply_text("会话已过期，请重新发送 /mydata。")
        return

    text = (message_text or "").strip()
    if not text:
        await update.effective_message.reply_text("请输入有效内容。")
        return

    text_value = None if text.startswith("/clear") else text
    if state_type == "nearby_edit_price":
        await update_profile(session, target_chat_id, user, price_text=(text_value[:128] if text_value else None))
    elif state_type == "nearby_edit_method":
        await update_profile(session, target_chat_id, user, method_text=(text_value[:128] if text_value else None))
    elif state_type == "nearby_edit_address":
        await update_profile(session, target_chat_id, user, address_text=(text_value[:500] if text_value else None))
    else:
        await update.effective_message.reply_text("当前状态不支持文本输入。")
        return

    await clear_user_state(session, state.chat_id, user.id)
    profile = await get_profile(session, target_chat_id, user.id)
    await update.effective_message.reply_text(
        "✅ 已更新。",
        reply_markup=nearby_manage_keyboard(target_chat_id, bool(profile.is_visible if profile else True)),
    )


async def handle_fsm_location_input_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    user = update.effective_user
    message = update.effective_message
    target_chat_id = int(state.state_data.get("target_chat_id", 0)) if state.state_data else 0
    if target_chat_id == 0:
        await message.reply_text("会话已过期，请重新发送 /mydata。")
        return

    if message.location is None:
        await message.reply_text("请直接发送 Telegram 定位消息。")
        return

    await update_profile(
        session,
        target_chat_id,
        user,
        latitude=message.location.latitude,
        longitude=message.location.longitude,
    )
    await clear_user_state(session, state.chat_id, user.id)

    profile = await get_profile(session, target_chat_id, user.id)
    await message.reply_text(
        "✅ 定位已更新。",
        reply_markup=nearby_manage_keyboard(target_chat_id, bool(profile.is_visible if profile else True)),
    )


async def start_edit_state_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    target_chat_id: int,
    field: str,
    *,
    reply_or_edit_func,
) -> None:
    if update.effective_user is None:
        return
    user = update.effective_user

    if update.effective_chat is None or update.effective_chat.type != "private":
        await reply_or_edit_func(update, "请私聊机器人发送 /mydata 后再编辑。")
        return

    state_map = {
        "price": ("nearby_edit_price", "请输入价格（支持数字或文本），输入 /clear 可清空。"),
        "method": ("nearby_edit_method", "请输入交付方式（如：自提/送货/远程），输入 /clear 可清空。"),
        "address": ("nearby_edit_address", "请输入详细地址或备注，输入 /clear 可清空。"),
        "location": ("nearby_edit_location", "请直接发送 Telegram 定位消息。"),
    }
    if field not in state_map:
        await reply_or_edit_func(update, "未知编辑项。")
        return

    state_type, prompt = state_map[field]
    async with db.session_factory() as session:
        await set_user_state(
            session,
            chat_id=user.id,
            user_id=user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    await reply_or_edit_func(update, prompt)


async def toggle_visible_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    target_chat_id: int,
    *,
    show_mydata_panel_func,
) -> None:
    if update.effective_user is None:
        return
    user = update.effective_user

    async with db.session_factory() as session:
        profile = await get_or_create_profile(
            session,
            target_chat_id,
            user=user,
            chat_type="supergroup" if target_chat_id < 0 else "private",
            chat_title=None,
        )
        profile.is_visible = not profile.is_visible
        await session.flush()
        await session.commit()

    await show_mydata_panel_func(update, context, target_chat_id)


async def handle_clear_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    target_chat_id: int,
    step: str,
    *,
    reply_or_edit_func,
    show_mydata_panel_func,
) -> None:
    if update.effective_user is None:
        return
    user = update.effective_user

    if step == "confirm":
        await reply_or_edit_func(
            update,
            "⚠️ 确认清空你的资料吗？此操作会清除位置、价格、方式和备注。",
            nearby_clear_confirm_keyboard(target_chat_id),
        )
        return

    if step == "cancel":
        await show_mydata_panel_func(update, context, target_chat_id)
        return

    if step != "do":
        await reply_or_edit_func(update, "未知操作。")
        return

    async with db.session_factory() as session:
        await clear_profile(session, target_chat_id, user.id)
        await clear_user_state(session, user.id, user.id)
        await session.commit()

    await show_mydata_panel_func(update, context, target_chat_id)
