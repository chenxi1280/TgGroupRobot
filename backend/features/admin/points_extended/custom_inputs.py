from __future__ import annotations

import re

from backend.shared.services.base import ValidationError

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)


async def handle_custom_points_input(
    update,
    context,
    session,
    state,
    message_text: str,
    *,
    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    state_type = state.state_type
    if state_type not in {"custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input"}:
        return False

    module = admin_module()
    user_id = update.effective_user.id
    text_value = message_text.strip()
    type_id = parse_state_int(state, "type_id")
    if type_id is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("自定义积分状态异常，已自动退出，请重新进入页面。")
        return True

    item = await module.PointsExtendedService.get_custom_point_type(session, target_chat_id, type_id)
    if item is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("自定义积分不存在，请重新进入页面。")
        return True

    if state_type == "custom_points_name_input":
        if not text_value:
            await update.effective_message.reply_text("积分名字不能为空。")
            return True
        try:
            await module.PointsExtendedService.update_custom_point_type(session, item, name=text_value[:64])
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
    elif state_type == "custom_points_rank_input":
        try:
            await module.PointsExtendedService.update_custom_point_type(
                session,
                item,
                rank_command=(None if text_value in {"", "清空"} else text_value[:32]),
            )
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return True
    else:
        parts = message_text.strip().split(maxsplit=2)
        if len(parts) < 2 or not re.fullmatch(r"-?\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
            await update.effective_message.reply_text("格式错误，请输入：用户ID 数量 备注(可选)")
            return True

        target_user_id = int(parts[0])
        amount = int(parts[1])
        if amount <= 0:
            await update.effective_message.reply_text("数量必须大于 0。")
            return True

        mode = state.state_data.get("mode")
        if mode not in {"add", "deduct"}:
            await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
            await session.commit()
            await update.effective_message.reply_text("自定义积分操作类型异常，已自动退出，请重新进入页面。")
            return True

        delta = amount if mode == "add" else -amount
        reason_note = parts[2].strip() if len(parts) >= 3 else None
        await module.ensure_user(
            session,
            user_id=target_user_id,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )
        balance = await module.PointsExtendedService.adjust_custom_points(
            session,
            chat_id=target_chat_id,
            type_id=item.id,
            user_id=target_user_id,
            delta=delta,
            operator_user_id=user_id,
            reason_note=reason_note,
        )
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        action_text = "增加" if delta > 0 else "扣除"
        await update.effective_message.reply_text(
            f"已为用户 {target_user_id} {action_text} {abs(delta)} {item.name}，当前余额 {balance}。"
        )
        await admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
        return True

    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
    return True
