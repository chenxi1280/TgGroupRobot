from __future__ import annotations

import re

from telegram import InlineKeyboardButton

from backend.features.activity.room_games.fees import (
    GAME_NAMES, MAX_ROOM_FEE, group_room_settings, update_group_room_settings,
)
from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService, is_user_admin
from backend.shared.ui.admin_keyboard import admin_keyboard
from backend.shared.ui.common.keyboard import toggle_row
from backend.shared.ui.menu_layout import navigation_row

ROOM_GAMES = ("sichuan", "zhajinhua")


async def can_configure_room_games(update, context, chat_id: int) -> bool:
    return (
        chat_id < 0
        and update.effective_chat is not None
        and update.effective_chat.type == "private"
        and update.effective_user is not None
        and await is_user_admin(context, chat_id, update.effective_user.id)
    )


async def show_room_game_settings(update, context, chat_id: int) -> None:
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await group_room_settings(session, chat_id)
    title = await admin_handler_instance()._get_chat_title(db, chat_id)
    lines = [f"🎮 {title} | 房间游戏设置", "", "服务费在建房时锁定，开场时向每位玩家扣除。"]
    menu = f"gm:rooms:{chat_id}"
    rows = []
    for game in ROOM_GAMES:
        terms = getattr(settings, game)
        lines.append(f"{GAME_NAMES[game]} · 每人每场 {terms.points} 分")
        rows.append(toggle_row(
            GAME_NAMES[game], enabled=terms.enabled, label_callback=f"{menu}:home",
            on_callback=f"{menu}:toggle:{game}:1", off_callback=f"{menu}:toggle:{game}:0",
        ))
    rows.append([
        InlineKeyboardButton(f"设置{GAME_NAMES[game]}服务费", callback_data=f"{menu}:fee:{game}")
        for game in ROOM_GAMES
    ])
    rows.append(navigation_row(f"gm:home:{chat_id}"))
    await MessageHelper.safe_edit(update, "\n".join(lines), reply_markup=admin_keyboard(rows))


async def handle_room_game_settings(update, context, chat_id: int, *, callback_data) -> None:
    if not await can_configure_room_games(update, context, chat_id):
        await MessageHelper.safe_edit(update, "请由本群管理员在机器人私聊中设置房间游戏。")
        return
    action, game = callback_data.get(3), callback_data.get(4)
    if action == "home":
        await show_room_game_settings(update, context, chat_id)
        return
    if game not in ROOM_GAMES:
        return
    user_id = update.effective_user.id
    if action == "fee":
        await admin_handler_instance()._start_text_input_state(
            context, user_id, user_id,
            state_type=ConversationStateType.game_wait_room_fee.value,
            payload={"target_chat_id": chat_id, "game": game},
        )
        await MessageHelper.safe_edit(
            update,
            f"🎮 房间游戏 | {GAME_NAMES[game]}服务费\n\n"
            f"请输入每人每场的服务费（0 至 {MAX_ROOM_FEE} 积分）\n例如：10\n0 表示免费。",
            reply_markup=admin_keyboard([navigation_row(f"gm:rooms:{chat_id}:home")]),
        )
        return
    enabled = callback_data.get(5)
    if action != "toggle" or enabled not in {"0", "1"}:
        return
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await update_group_room_settings(session, chat_id, user_id=user_id, game=game, enabled=enabled == "1")
        await session.commit()
    await show_room_game_settings(update, context, chat_id)


async def handle_room_fee_input(update, context, session, *, state, message_text: str) -> None:
    chat_id, game = state.state_data.get("target_chat_id"), state.state_data.get("game")
    user_id = update.effective_user.id
    if not isinstance(chat_id, int) or game not in ROOM_GAMES:
        raise ValidationError("请重新打开房间游戏设置。")
    if not await can_configure_room_games(update, context, chat_id) or not await PermissionPolicyService.can_manage(
        context, chat_id, user_id,
    ):
        await clear_private_admin_state(session, target_chat_id=chat_id, user_id=user_id)
        await session.commit()
        await MessageHelper.safe_edit(update, "本群管理权限已失效。")
        return
    value = message_text.strip()
    if not re.fullmatch(r"[0-9]{1,6}", value) or int(value) > MAX_ROOM_FEE:
        raise ValidationError("服务费须为 0 至 100000 之间的整数。")
    await update_group_room_settings(session, chat_id, user_id=user_id, game=game, points=int(value))
    await clear_private_admin_state(session, target_chat_id=chat_id, user_id=user_id)
    await session.commit()
    await show_room_game_settings(update, context, chat_id)
