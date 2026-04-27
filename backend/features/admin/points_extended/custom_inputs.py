from __future__ import annotations

import re

from backend.shared.services.base import ValidationError

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)
from backend.shared.services.formatters import format_user_display_name


def _forwarded_user(message):
    user = getattr(message, "forward_from", None)
    if user is not None:
        return user

    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None
    return getattr(origin, "sender_user", None)


def _user_label_from_telegram_user(user) -> str:
    return format_user_display_name(user, user.id)


def _target_label(raw_value: str, target_user_id: int) -> str:
    return str(target_user_id) if raw_value.lstrip("-").isdigit() else raw_value


def _is_adjust_mode(value) -> bool:
    return value in {"add", "deduct"}


async def _resolve_adjust_target(module, session, message, raw_value: str) -> tuple[int, str, bool] | None:
    forwarded_user = _forwarded_user(message)
    if forwarded_user is not None:
        target_user_id = int(forwarded_user.id)
        await module.ensure_user(
            session,
            user_id=target_user_id,
            username=forwarded_user.username,
            first_name=forwarded_user.first_name,
            last_name=forwarded_user.last_name,
            language_code=forwarded_user.language_code,
        )
        return target_user_id, _user_label_from_telegram_user(forwarded_user), True

    if not raw_value:
        return None

    target_user_id = await module.PointsExtendedService.resolve_user_id(session, raw_value)
    if target_user_id is None:
        return None
    return target_user_id, _target_label(raw_value, target_user_id), False


async def _prompt_custom_points_amount(
    module,
    session,
    update,
    context,
    state,
    item,
    target_chat_id: int,
    user_id: int,
    mode: str,
    raw_message_text: str,
) -> None:
    message_text = (
        getattr(update.effective_message, "text", None)
        or getattr(update.effective_message, "caption", None)
        or raw_message_text
        or ""
    )
    parts = message_text.strip().split(maxsplit=2)
    raw_target = parts[0] if parts else ""
    resolved = await _resolve_adjust_target(module, session, update.effective_message, raw_target)
    if resolved is None:
        await update.effective_message.reply_text("未找到该用户，请输入用户ID、已记录的用户名，或转发成员消息。")
        return

    target_user_id, target_label, from_forward = resolved
    if not from_forward and len(parts) >= 2 and re.fullmatch(r"\d+", parts[1]):
        await _apply_custom_points_adjustment(
            module,
            session,
            update,
            context,
            item,
            target_chat_id=target_chat_id,
            user_id=user_id,
            target_user_id=target_user_id,
            target_label=target_label,
            mode=mode,
            amount_text=parts[1],
            reason_note=parts[2].strip() if len(parts) >= 3 else None,
        )
        return

    balance = await module.PointsExtendedService.get_custom_point_balance(
        session,
        chat_id=target_chat_id,
        type_id=item.id,
        user_id=target_user_id,
    )
    await module.set_user_state(
        session,
        chat_id=state.chat_id,
        user_id=user_id,
        state_type=state.state_type,
        state_data={
            **(state.state_data or {}),
            "target_user_id": target_user_id,
            "target_label": target_label,
        },
    )
    action_text = "增加积分" if mode == "add" else "扣除积分"
    await update.effective_message.reply_text(
        f"{action_text}\n\n{target_label} => {balance}\n\n👉 输入数量："
    )


async def _apply_custom_points_adjustment(
    module,
    session,
    update,
    context,
    item,
    *,
    target_chat_id: int,
    user_id: int,
    target_user_id: int,
    target_label: str,
    mode: str,
    amount_text: str,
    reason_note: str | None = None,
) -> bool:
    if not _is_adjust_mode(mode):
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("自定义积分操作类型异常，已自动退出，请重新进入页面。")
        return True

    if not re.fullmatch(r"\d+", amount_text):
        await update.effective_message.reply_text("格式错误，请输入数量。")
        return False

    amount = int(amount_text)
    if amount <= 0:
        await update.effective_message.reply_text("数量必须大于 0。")
        return False

    delta = amount if mode == "add" else -amount
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
        f"已为用户 {target_label} {action_text} {abs(delta)} {item.name}，当前余额 {balance}。"
    )
    if context is not None:
        await admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
    return True


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
            normalized_name = text_value[:64]
            current_auto_rank_command = module.PointsExtendedService.default_custom_point_rank_command(item.name)
            update_kwargs = {"name": normalized_name}
            if not item.rank_command or item.rank_command == current_auto_rank_command:
                update_kwargs["rank_command"] = module.PointsExtendedService.default_custom_point_rank_command(
                    normalized_name
                )
            await module.PointsExtendedService.update_custom_point_type(session, item, **update_kwargs)
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
        mode = state.state_data.get("mode")
        if not _is_adjust_mode(mode):
            await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
            await session.commit()
            await update.effective_message.reply_text("自定义积分操作类型异常，已自动退出，请重新进入页面。")
            return True

        target_user_id = state.state_data.get("target_user_id")
        if target_user_id is None:
            await _prompt_custom_points_amount(
                module,
                session,
                update,
                context,
                state,
                item,
                target_chat_id,
                user_id,
                mode,
                message_text,
            )
            return True

        try:
            target_user_id_value = int(target_user_id)
        except (TypeError, ValueError):
            await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
            await session.commit()
            await update.effective_message.reply_text("自定义积分目标用户异常，已自动退出，请重新进入页面。")
            return True

        parts = message_text.strip().split(maxsplit=1)
        if not parts:
            await update.effective_message.reply_text("格式错误，请输入数量。")
            return True
        await _apply_custom_points_adjustment(
            module,
            session,
            update,
            context,
            item,
            target_chat_id=target_chat_id,
            user_id=user_id,
            target_user_id=target_user_id_value,
            target_label=str(state.state_data.get("target_label") or target_user_id),
            mode=mode,
            amount_text=parts[0],
            reason_note=parts[1].strip() if len(parts) >= 2 else None,
        )
        return True

    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
    return True
