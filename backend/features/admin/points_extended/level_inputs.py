from __future__ import annotations

import re

from backend.shared.services.base import ValidationError

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)


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
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("积分等级状态异常，已自动退出，请重新进入页面。")
        return True

    level = await module.PointsExtendedService.get_level(session, target_chat_id, level_id)
    if level is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("积分等级不存在，请重新进入页面。")
        return True

    if state.state_type == "points_level_name_input":
        if not text_value:
            await update.effective_message.reply_text("等级名称不能为空。")
            return True
        try:
            await module.PointsExtendedService.update_level(session, level, level_name=text_value[:64])
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
    else:
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("积分门槛必须是大于 0 的整数。")
            return True
        threshold_value = int(text_value)
        if threshold_value <= 0:
            await update.effective_message.reply_text("积分门槛必须大于 0。")
            return True
        try:
            await module.PointsExtendedService.update_level(session, level, point_threshold=threshold_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True

    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_points_level_detail(update, context, target_chat_id, level_id=level.id)
    return True
