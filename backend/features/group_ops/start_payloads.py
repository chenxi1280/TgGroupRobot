"""私聊 `/start <payload>` 深链入口。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import InviteLink, TgChat
from backend.platform.db.schema.models.enums import ConversationStateType, InviteLinkStatus
from backend.platform.state.conversation_state_service import SELECTED_CHAT_STATE
from backend.platform.state.state_service import get_user_state, set_user_state

START_PAYLOAD_PARTS = 2


def extract_start_payload(text: str | None) -> str:
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) == START_PAYLOAD_PARTS else ""


async def handle_invite_relay_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("inv_"):
        return False
    try:
        link_id = int(payload.removeprefix("inv_"))
    except ValueError:
        await update.effective_message.reply_text("邀请链接无效，请重新获取。")
        return True
    link = await _load_invite_link(context, link_id)
    if not _is_active_invite(link):
        await update.effective_message.reply_text("邀请链接已失效，请重新获取。")
        return True
    _cache_invite_context(context, update.effective_user.id, link)
    await update.effective_message.reply_text(
        "🔗 邀请链接已准备好\n\n点击下方按钮进入群组，审核通过后会自动计入邀请统计。",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("进入群组", url=link.invite_link)],
        ]),
    )
    return True


async def _load_invite_link(context: ContextTypes.DEFAULT_TYPE, link_id: int):
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await session.execute(select(InviteLink).where(InviteLink.id == link_id))
        link = result.scalar_one_or_none()
        await session.commit()
    return link


def _is_active_invite(link) -> bool:
    if link is None or link.status != InviteLinkStatus.active.value:
        return False
    return link.expire_date is None or link.expire_date >= dt.datetime.now(dt.UTC)


def _cache_invite_context(context, user_id: int, link) -> None:
    user_data = getattr(context, "user_data", None)
    if isinstance(user_data, dict):
        user_data["pending_invite_link_id"] = link.id
    from backend.features.verification.verification_join_guards import cache_invite_join_hint

    cache_invite_join_hint(
        context,
        chat_id=link.chat_id,
        user_id=user_id,
        invite_link=link.invite_link,
    )


async def _location_state_data(session, *, user_id: int, target_chat_id: int) -> dict:
    existing = await get_user_state(session, chat_id=user_id, user_id=user_id)
    state_data = {"target_chat_id": target_chat_id}
    if existing is None or existing.state_type != SELECTED_CHAT_STATE:
        return state_data
    if not isinstance(existing.state_data, dict):
        return state_data
    selected_chat_id = existing.state_data.get("managed_chat_id")
    if isinstance(selected_chat_id, int):
        state_data["previous_selected_chat_id"] = selected_chat_id
    return state_data


async def handle_teacher_location_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("tloc_"):
        return False
    try:
        target_chat_id = int(payload.removeprefix("tloc_"))
    except ValueError:
        await update.effective_message.reply_text("定位入口无效，请回群重新点击“私聊更新定位”。")
        return True
    target_chat, error = await _prepare_member_location_state(
        context,
        user_id=update.effective_user.id,
        target_chat_id=target_chat_id,
    )
    if error:
        await update.effective_message.reply_text(error)
        return True
    await update.effective_message.reply_text(
        _member_location_prompt(target_chat.title or str(target_chat_id)),
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


async def _prepare_member_location_state(
    context,
    *,
    user_id: int,
    target_chat_id: int,
):
    from backend.platform.db.schema.models.garage_features import TeacherSearchSetting

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat = await session.get(TgChat, target_chat_id)
        setting = await session.get(TeacherSearchSetting, target_chat_id) if target_chat else None
        if target_chat is None:
            await session.commit()
            return None, "定位入口已失效，请回群重新点击“私聊更新定位”。"
        if setting is None or not setting.nearby_search_enabled:
            await session.commit()
            return None, "该群暂未启用附近搜索。"
        state_data = await _location_state_data(
            session,
            user_id=user_id,
            target_chat_id=target_chat_id,
        )
        await set_user_state(
            session,
            chat_id=user_id,
            user_id=user_id,
            state_type=ConversationStateType.teacher_search_member_location_input.value,
            state_data=state_data,
        )
        await session.commit()
    return target_chat, None


def _member_location_prompt(title: str) -> str:
    return (
        "📍 更新附近搜索定位\n\n"
        f"目标群：{title}\n\n"
        "请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。\n"
        "定位只用于附近老师搜索，不会在群里公开。"
    )


async def handle_teacher_self_location_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return False
    if not payload.startswith("tselfloc_"):
        return False
    try:
        target_chat_id = int(payload.removeprefix("tselfloc_"))
    except ValueError:
        await update.effective_message.reply_text("老师定位入口无效，请回群重新点击。")
        return True
    target_chat, error = await _prepare_teacher_location_state(
        context,
        user_id=update.effective_user.id,
        target_chat_id=target_chat_id,
    )
    if error:
        await update.effective_message.reply_text(error)
        return True
    await update.effective_message.reply_text(
        _teacher_location_prompt(target_chat.title or str(target_chat_id)),
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


async def _prepare_teacher_location_state(context, *, user_id: int, target_chat_id: int):
    from backend.features.garage.services.garage_features_service import GarageAuthService

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat = await session.get(TgChat, target_chat_id)
        if target_chat is None:
            await session.commit()
            return None, "老师定位入口已失效，请回群重新点击。"
        certified = await GarageAuthService.is_effective_certified_teacher(
            session,
            target_chat_id,
            user_id,
        )
        if not certified:
            await session.commit()
            return None, "你不是该群的认证老师，无法更新老师服务定位。"
        await set_user_state(
            session,
            chat_id=user_id,
            user_id=user_id,
            state_type=ConversationStateType.teacher_self_location_input.value,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()
    return target_chat, None


def _teacher_location_prompt(title: str) -> str:
    return (
        "📍 更新老师服务定位\n\n"
        f"目标群：{title}\n\n"
        "请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。\n"
        "该定位用于老师附近搜索，不会覆盖你的群友附近查询定位。"
    )


async def handle_car_review_submit_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> bool:
    if not payload.startswith("crvsub_"):
        return False
    try:
        target_chat_id = int(payload.removeprefix("crvsub_"))
    except ValueError:
        if update.effective_message is not None:
            await update.effective_message.reply_text("车评提交入口无效，请回群重新点击“提交车评”。")
        return True
    from backend.features.admin.garage.review_submit import start_car_review_submit_flow

    return await start_car_review_submit_flow(update, context, target_chat_id)
