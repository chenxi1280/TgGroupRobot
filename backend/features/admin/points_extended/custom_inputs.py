from __future__ import annotations

import re
from dataclasses import dataclass

from backend.shared.services.base import ValidationError

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)
from backend.shared.services.formatters import format_user_display_name
_AMOUNT_WITH_REASON_PARTS = 2
_TARGET_WITH_AMOUNT_PARTS = 2
_TARGET_WITH_REASON_PARTS = 3
_CUSTOM_POINT_NAME_LENGTH = 64
_CUSTOM_POINT_RANK_COMMAND_LENGTH = 32



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


@dataclass(frozen=True)
class _CustomPointInput:
    module: object
    session: object
    update: object
    context: object
    state: object
    item: object
    target_chat_id: int
    user_id: int


async def _exit_custom_input(input_data: _CustomPointInput, message: str) -> None:
    await clear_points_state(
        input_data.session,
        target_chat_id=input_data.target_chat_id,
        user_id=input_data.user_id,
    )
    await input_data.session.commit()
    await input_data.update.effective_message.reply_text(message)


async def _resolve_adjust_target(module, session, message, *, raw_value: str) -> tuple[int, str, bool] | None:
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


def _adjustment_message_text(input_data: _CustomPointInput, raw_message_text: str) -> str:
    message = input_data.update.effective_message
    return getattr(message, "text", None) or getattr(message, "caption", None) or raw_message_text or ""


def _inline_adjustment(parts: list[str], from_forward: bool) -> tuple[str, str | None] | None:
    if from_forward or len(parts) < _TARGET_WITH_AMOUNT_PARTS:
        return None
    if not re.fullmatch(r"\d+", parts[1]):
        return None
    reason = parts[2].strip() if len(parts) >= _TARGET_WITH_REASON_PARTS else None
    return parts[1], reason


async def _store_adjustment_target(
    input_data: _CustomPointInput,
    *,
    target_user_id: int,
    target_label: str,
    mode: str,
) -> None:
    balance = await input_data.module.PointsExtendedService.get_custom_point_balance(
        input_data.session,
        chat_id=input_data.target_chat_id,
        type_id=input_data.item.id,
        user_id=target_user_id,
    )
    await input_data.module.set_user_state(
        input_data.session,
        chat_id=input_data.state.chat_id,
        user_id=input_data.user_id,
        state_type=input_data.state.state_type,
        state_data={
            **(input_data.state.state_data or {}),
            "target_user_id": target_user_id,
            "target_label": target_label,
        },
    )
    action_text = "增加积分" if mode == "add" else "扣除积分"
    await input_data.update.effective_message.reply_text(f"{action_text}\n\n{target_label} => {balance}\n\n👉 输入数量：")


async def _prompt_custom_points_amount(
    input_data: _CustomPointInput,
    *,
    mode: str,
    raw_message_text: str,
) -> None:
    update = input_data.update
    message_text = _adjustment_message_text(input_data, raw_message_text)
    parts = message_text.strip().split(maxsplit=2)
    raw_target = parts[0] if parts else ""
    resolved = await _resolve_adjust_target(
        input_data.module,
        input_data.session,
        update.effective_message,
        raw_value=raw_target,
    )
    if resolved is None:
        await update.effective_message.reply_text("未找到该用户，请输入用户ID、已记录的用户名，或转发成员消息。")
        return
    target_user_id, target_label, from_forward = resolved
    inline_adjustment = _inline_adjustment(parts, from_forward)
    if inline_adjustment is not None:
        amount_text, reason_note = inline_adjustment
        await _apply_custom_points_adjustment(
            input_data,
            target_user_id=target_user_id,
            target_label=target_label,
            mode=mode,
            amount_text=amount_text,
            reason_note=reason_note,
        )
        return
    await _store_adjustment_target(
        input_data,
        target_user_id=target_user_id,
        target_label=target_label,
        mode=mode,
    )


async def _validated_adjustment_delta(input_data: _CustomPointInput, mode: str, amount_text: str) -> int | None:
    if not _is_adjust_mode(mode):
        await _exit_custom_input(input_data, "自定义积分操作类型异常，已自动退出，请重新进入页面。")
        return None
    if not re.fullmatch(r"\d+", amount_text):
        await input_data.update.effective_message.reply_text("格式错误，请输入数量。")
        return None
    amount = int(amount_text)
    if amount <= 0:
        await input_data.update.effective_message.reply_text("数量必须大于 0。")
        return None
    return amount if mode == "add" else -amount


async def _apply_custom_points_adjustment(
    input_data: _CustomPointInput,
    *,
    target_user_id: int,
    target_label: str,
    mode: str,
    amount_text: str,
    reason_note: str | None = None,
) -> bool:
    delta = await _validated_adjustment_delta(input_data, mode, amount_text)
    if delta is None:
        return False
    await input_data.module.ensure_user(
        input_data.session,
        user_id=target_user_id,
        username=None,
        first_name=None,
        last_name=None,
        language_code=None,
    )
    balance = await input_data.module.PointsExtendedService.adjust_custom_points(
        input_data.session,
        chat_id=input_data.target_chat_id,
        type_id=input_data.item.id,
        user_id=target_user_id,
        delta=delta,
        operator_user_id=input_data.user_id,
        reason_note=reason_note,
    )
    await clear_points_state(
        input_data.session,
        target_chat_id=input_data.target_chat_id,
        user_id=input_data.user_id,
    )
    await input_data.session.commit()
    action_text = "增加" if delta > 0 else "扣除"
    await input_data.update.effective_message.reply_text(
        f"已为用户 {target_label} {action_text} {abs(delta)} {input_data.item.name}，当前余额 {balance}。"
    )
    if input_data.context is not None:
        await admin_handler_instance()._show_custom_point_detail(
            input_data.update,
            input_data.context,
            input_data.target_chat_id,
            type_id=input_data.item.id,
        )
    return True


async def _load_custom_point_input(update, context, session, *, state, target_chat_id: int) -> _CustomPointInput | None:
    module = admin_module()
    user_id = update.effective_user.id
    type_id = parse_state_int(state, "type_id")
    if type_id is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("自定义积分状态异常，已自动退出，请重新进入页面。")
        return None
    item = await module.PointsExtendedService.get_custom_point_type(session, target_chat_id, type_id)
    if item is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("自定义积分不存在，请重新进入页面。")
        return None
    return _CustomPointInput(
        module=module,
        session=session,
        update=update,
        context=context,
        state=state,
        item=item,
        target_chat_id=target_chat_id,
        user_id=user_id,
    )


async def _update_custom_point_name(input_data: _CustomPointInput, text_value: str) -> bool:
    if not text_value:
        await input_data.update.effective_message.reply_text("积分名字不能为空。")
        return False
    try:
        normalized_name = text_value[:_CUSTOM_POINT_NAME_LENGTH]
        service = input_data.module.PointsExtendedService
        current_auto_rank = service.default_custom_point_rank_command(input_data.item.name)
        update_kwargs = {"name": normalized_name}
        if not input_data.item.rank_command or input_data.item.rank_command == current_auto_rank:
            update_kwargs["rank_command"] = service.default_custom_point_rank_command(normalized_name)
        await service.update_custom_point_type(input_data.session, input_data.item, **update_kwargs)
        return True
    except ValidationError as exc:
        await input_data.update.effective_message.reply_text(str(exc))
        return False


async def _update_custom_point_rank(input_data: _CustomPointInput, text_value: str) -> bool:
    rank_command = None if text_value in {"", "清空"} else text_value[:_CUSTOM_POINT_RANK_COMMAND_LENGTH]
    try:
        await input_data.module.PointsExtendedService.update_custom_point_type(
            input_data.session,
            input_data.item,
            rank_command=rank_command,
        )
        return True
    except ValidationError as exc:
        await input_data.update.effective_message.reply_text(str(exc))
        return False


async def _finish_custom_point_input(input_data: _CustomPointInput) -> None:
    await clear_points_state(
        input_data.session,
        target_chat_id=input_data.target_chat_id,
        user_id=input_data.user_id,
    )
    await input_data.session.commit()
    await admin_handler_instance()._show_custom_point_detail(
        input_data.update,
        input_data.context,
        input_data.target_chat_id,
        type_id=input_data.item.id,
    )


async def _handle_custom_point_adjustment(input_data: _CustomPointInput, message_text: str) -> None:
    mode = input_data.state.state_data.get("mode")
    if not _is_adjust_mode(mode):
        await _exit_custom_input(input_data, "自定义积分操作类型异常，已自动退出，请重新进入页面。")
        return
    target_user_id = input_data.state.state_data.get("target_user_id")
    if target_user_id is None:
        await _prompt_custom_points_amount(input_data, mode=mode, raw_message_text=message_text)
        return
    try:
        target_user_id_value = int(target_user_id)
    except (TypeError, ValueError):
        await _exit_custom_input(input_data, "自定义积分目标用户异常，已自动退出，请重新进入页面。")
        return
    parts = message_text.strip().split(maxsplit=1)
    if not parts:
        await input_data.update.effective_message.reply_text("格式错误，请输入数量。")
        return
    await _apply_custom_points_adjustment(
        input_data,
        target_user_id=target_user_id_value,
        target_label=str(input_data.state.state_data.get("target_label") or target_user_id),
        mode=mode,
        amount_text=parts[0],
        reason_note=parts[1].strip() if len(parts) >= _AMOUNT_WITH_REASON_PARTS else None,
    )


async def handle_custom_points_input(
    update, context, session, *, state, message_text: str, target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True
    state_type = state.state_type
    supported_states = {"custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input"}
    if state_type not in supported_states:
        return False
    input_data = await _load_custom_point_input(
        update,
        context,
        session,
        state=state,
        target_chat_id=target_chat_id,
    )
    if input_data is None:
        return True
    text_value = message_text.strip()
    if state_type == "custom_points_adjust_input":
        await _handle_custom_point_adjustment(input_data, message_text)
        return True
    if state_type == "custom_points_name_input":
        updated = await _update_custom_point_name(input_data, text_value)
    else:
        updated = await _update_custom_point_rank(input_data, text_value)
    if updated:
        await _finish_custom_point_input(input_data)
    return True
