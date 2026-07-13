from __future__ import annotations

import re

from backend.shared.services.base import ValidationError

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)


async def _exit_invalid_level_state(
    update, session, *, target_chat_id: int, user_id: int, message: str
) -> None:
    await clear_points_state(
        session, target_chat_id=target_chat_id, user_id=user_id
    )
    await session.commit()
    await update.effective_message.reply_text(message)


async def _apply_level_input(update, *, service, session, state_type: str, level, text: str) -> bool:
    if state_type == "points_level_name_input":
        if not text:
            await update.effective_message.reply_text("等级名称不能为空。")
            return False
        changes = {"level_name": text[:64]}
    else:
        if not re.fullmatch(r"\d+", text):
            await update.effective_message.reply_text("积分门槛必须是大于 0 的整数。")
            return False
        threshold = int(text)
        if threshold <= 0:
            await update.effective_message.reply_text("积分门槛必须大于 0。")
            return False
        changes = {"point_threshold": threshold}
    try:
        await service.update_level(session, level, **changes)
        return True
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return False


async def handle_points_level_input(
    update,
    context,
    session,
    *, state,
    message_text: str,

    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    if state.state_type not in {"points_level_name_input", "points_level_threshold_input"}:
        return False

    module = admin_module()
    user_id = update.effective_user.id
    text_value = message_text.strip()
    level_id = parse_state_int(state, "level_id")
    if level_id is None:
        await _exit_invalid_level_state(
            update, session, target_chat_id=target_chat_id, user_id=user_id,
            message="积分等级状态异常，已自动退出，请重新进入页面。",
        )
        return True

    level = await module.PointsExtendedService.get_level(session, target_chat_id, level_id)
    if level is None:
        await _exit_invalid_level_state(
            update, session, target_chat_id=target_chat_id, user_id=user_id,
            message="积分等级不存在，请重新进入页面。",
        )
        return True
    if not await _apply_level_input(
        update, service=module.PointsExtendedService, session=session,
        state_type=state.state_type, level=level, text=text_value,
    ):
        return True

    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_points_level_detail(update, context, target_chat_id, level_id=level.id)
    return True
