from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import admin_handler_instance
from backend.features.admin.garage.teacher_search_inputs import (
    _extract_location_pair_from_message,
)
from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchService
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state
from backend.shared.callback_parser import CallbackParser

SELF_LOCATION_STATE = ConversationStateType.teacher_self_location_input.value
SELF_STATE_TYPES = {
    SELF_LOCATION_STATE,
}


def _teacher_self_list_keyboard(chat_rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(title[:48], callback_data=f"teacher:self:home:{chat_id}")]
        for chat_id, title in chat_rows
    ]
    return InlineKeyboardMarkup(rows)


def _teacher_self_home_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 更新服务定位", callback_data=f"teacher:self:location:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data="teacher:self:list")],
    ])


async def _clear_teacher_self_state(session, user_id: int) -> None:
    await clear_user_state(session, chat_id=user_id, user_id=user_id)


async def _load_teacher_home_data(session, *, chat_id: int, user_id: int):
    profile = await TeacherSearchService.get_teacher_profile(session, chat_id, user_id)
    pool_info = await GarageAuthService.get_teacher_pool_info(session, chat_id)
    return profile, pool_info


async def show_teacher_self_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    empty_text: str | None = None,
) -> None:
    if update.effective_user is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rows = await GarageAuthService.list_teacher_self_service_chats(session, update.effective_user.id)
        await session.commit()

    if not rows:
        text = empty_text or "你当前还不是任何群的认证老师。"
        await admin_handler_instance().message_helper.safe_edit(update, text)
        return

    chat_rows = [(chat.id, chat.title or str(chat.id)) for chat, _ in rows]
    text_lines = [
        "👩‍🏫 老师资料维护",
        "",
        "请选择要维护资料的群：",
    ]
    await admin_handler_instance().message_helper.safe_edit(
        update,
        "\n".join(text_lines),
        reply_markup=_teacher_self_list_keyboard(chat_rows),
    )


def _teacher_self_home_text(profile, pool_info, *, chat_title: str) -> str:
    has_labels = profile is not None and bool(profile.labels)
    labels = " / ".join(profile.labels) if has_labels else "未设置"
    has_location = (
        profile is not None and profile.latitude is not None
        and profile.longitude is not None
    )
    region = profile.region_text if profile and profile.region_text else "未设置"
    price = profile.price_text if profile and profile.price_text else "未设置"
    return "\n".join([
        "👩‍🏫 老师资料维护", "", f"群组：{chat_title}",
        f"认证来源：{pool_info.display_text}",
        f"服务定位：{'已设置' if has_location else '未设置'}",
        f"地区/地址：{region}", f"价格：{price}", f"服务标签：{labels}", "",
        "资料由管理员维护；老师本人仅可更新服务定位。",
    ])


async def show_teacher_self_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    if update.effective_user is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        is_teacher = await GarageAuthService.is_effective_certified_teacher(session, chat_id, update.effective_user.id)
        if not is_teacher:
            await session.commit()
            await show_teacher_self_list(
                update,
                context,
                empty_text="你已不在该群的认证老师名单中，请重新选择可维护的群。",
            )
            return
        profile, pool_info = await _load_teacher_home_data(
            session,
            chat_id=chat_id,
            user_id=update.effective_user.id,
        )
        await session.commit()

    chat_title = await _resolve_chat_title(context, chat_id)
    await admin_handler_instance().message_helper.safe_edit(
        update, _teacher_self_home_text(profile, pool_info, chat_title=chat_title),
        reply_markup=_teacher_self_home_keyboard(chat_id),
    )


async def _resolve_chat_title(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        from backend.platform.db.schema.models.core import TgChat

        chat = await session.get(TgChat, chat_id)
        await session.commit()
    if chat is not None and chat.title:
        return chat.title
    return str(chat_id)


async def _start_teacher_self_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    state_type: str,
    prompt_text: str,
) -> None:
    if update.effective_user is None:
        return
    await admin_handler_instance()._start_text_input_state(
        context,
        update.effective_user.id,
        update.effective_user.id,
        state_type=state_type,
        payload={"target_chat_id": chat_id},
    )
    await admin_handler_instance().message_helper.safe_edit(
        update,
        prompt_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回", callback_data=f"teacher:self:home:{chat_id}")]
        ]),
    )


async def _resolve_teacher_self_chat(update, context, callback) -> int | None:
    chat_id = callback.get_int_optional(3)
    if chat_id is None:
        await admin_handler_instance().message_helper.safe_edit(
            update, "老师资料入口参数无效，请重新进入。"
        )
        return None
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        is_teacher = await GarageAuthService.is_effective_certified_teacher(
            session, chat_id, update.effective_user.id
        )
        await session.commit()
    if is_teacher:
        return chat_id
    await show_teacher_self_list(
        update, context,
        empty_text="你已不在该群的认证老师名单中，请重新选择可维护的群。",
    )
    return None


async def _dispatch_teacher_self_action(update, context, *, action: str, chat_id: int) -> None:
    if action == "home":
        await show_teacher_self_home(update, context, chat_id)
        return
    if action == "location":
        await _start_teacher_self_state(
            update, context, chat_id=chat_id, state_type=SELF_LOCATION_STATE,
            prompt_text=(
                "📍 更新服务定位\n\n请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。\n"
                "该定位用于老师附近搜索，不会同步成群友自己的查询定位。"
            ),
        )
        return
    if action in {"region", "price", "labels"}:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"teacher:self:home:{chat_id}")]]
        )
        await admin_handler_instance().message_helper.safe_edit(
            update, "老师资料由管理员维护；老师本人仅可更新服务定位。",
            reply_markup=keyboard,
        )
        return
    await show_teacher_self_list(update, context)


async def teacher_self_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return
    if update.effective_chat.type != "private":
        await admin_handler_instance().message_helper.safe_edit(update, "请在私聊中使用此功能。")
        return

    callback = CallbackParser.parse(update.callback_query.data or "")
    if callback.get(0) != "teacher" or callback.get(1) != "self":
        return

    action = callback.get(2)
    if action == "list":
        await show_teacher_self_list(update, context)
        return

    chat_id = await _resolve_teacher_self_chat(update, context, callback)
    if chat_id is None:
        return
    await _dispatch_teacher_self_action(
        update, context, action=action, chat_id=chat_id
    )


async def handle_teacher_self_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = (state.state_data or {}).get("target_chat_id")
    if not isinstance(target_chat_id, int):
        await _clear_teacher_self_state(session, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("老师资料状态异常，请重新进入。", reply_markup=ReplyKeyboardRemove())
        return

    if not await GarageAuthService.is_effective_certified_teacher(session, target_chat_id, update.effective_user.id):
        await _clear_teacher_self_state(session, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(
            "你已不在该群的认证老师名单中，请重新进入。",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    state_type = state.state_type
    if state_type == SELF_LOCATION_STATE:
        location_pair = await _extract_location_pair_from_message(update.effective_message, message_text)
        if location_pair is None:
            await update.effective_message.reply_text(
                "请发送 Telegram 位置或共享地点，也可以粘贴 Google 地图定位链接。",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await TeacherSearchService.upsert_teacher_profile_from_location(
            session,
            chat_id=target_chat_id,
            user_id=update.effective_user.id,
            latitude=location_pair[0],
            longitude=location_pair[1],
        )
        await _clear_teacher_self_state(session, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("✅ 已更新该群的服务定位。", reply_markup=ReplyKeyboardRemove())
        await show_teacher_self_home(update, context, target_chat_id)
        return

    await _clear_teacher_self_state(session, update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("老师资料状态异常，请重新进入。", reply_markup=ReplyKeyboardRemove())
