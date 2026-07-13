from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_subscription import (
    parse_lottery_subscribe_targets,
)
from backend.features.activity.lottery_creation_config import (
    _next_step_after_draw_param,
    _next_step_after_points,
    _state_data,
)
from backend.features.activity.lottery_creation_parsing import (
    PRESET_CLEAR_WORDS,
    _parse_future_time,
    _parse_non_negative_int,
    _parse_positive_int,
    _parse_preset_winner_refs_from_values,
    _prize_slot_count,
)
from backend.features.activity.lottery_creation_wizard_prompts import (
    _reply_next_prompt,
)


@dataclass(frozen=True, slots=True)
class WizardMessageRequest:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    state: object
    data: dict
    text: str
    resolve_username: object
    validate_subscribe: object


MessageHandler = Callable[[WizardMessageRequest], object]


async def _advance_message(
    request: WizardMessageRequest,
    data: dict,
    next_step: str,
) -> None:
    await _reply_next_prompt(
        request.update,
        request.session,
        request.state,
        data=data,
        next_step=next_step,
    )


async def _handle_title(request: WizardMessageRequest) -> None:
    title_line = request.text.strip()
    title, separator, description = title_line.partition("|")
    if not title.strip():
        raise ValueError("抽奖名称不能为空")
    data = {
        **request.data,
        "title": title.strip(),
        "description": description.strip() if separator else None,
    }
    await _advance_message(request, data, "prize_name")


async def _handle_subscribe_targets(request: WizardMessageRequest) -> None:
    targets = parse_lottery_subscribe_targets(request.text)
    validated = await request.validate_subscribe(request.context, targets)
    await _advance_message(
        request,
        {**request.data, "subscribe_targets": validated},
        "preset_confirm",
    )


async def _handle_prize_name(request: WizardMessageRequest) -> None:
    prize_name = request.text.strip()
    if not prize_name:
        raise ValueError("奖品名称不能为空")
    existing_names = {
        str(prize.get("name") or "").strip()
        for prize in request.data.get("prizes") or []
    }
    if prize_name in existing_names:
        raise ValueError(f"奖品名称不能重复：{prize_name}")
    await _advance_message(
        request,
        {**request.data, "pending_prize_name": prize_name[:128]},
        "prize_quantity",
    )


async def _handle_prize_quantity(request: WizardMessageRequest) -> None:
    quantity = _parse_positive_int(request.text, "中奖人数/份数")
    prize_name = str(request.data.get("pending_prize_name") or "").strip()
    if not prize_name:
        raise ValueError("奖品名称丢失，请重新开始创建")
    prize = {"name": prize_name, "quantity": quantity, "points_reward": 0}
    data = {
        key: value
        for key, value in request.data.items()
        if key != "pending_prize_name"
    }
    await _advance_message(
        request,
        {**data, "prizes": [*(data.get("prizes") or []), prize]},
        "prize_action",
    )


async def _handle_button_only(request: WizardMessageRequest) -> None:
    messages = {
        "prize_action": "请使用按钮选择继续添加奖品，或完成奖品设置。",
        "point_type": "请使用按钮选择积分类型。",
    }
    await request.update.effective_message.reply_text(messages[str(request.data.get("step"))])


async def _handle_draw_param(request: WizardMessageRequest) -> None:
    if request.data.get("draw_trigger") == "full_participants":
        data = {
            **request.data,
            "max_participants": _parse_positive_int(request.text, "满员人数"),
        }
    else:
        data = {
            **request.data,
            "draw_time": _parse_future_time(request.text).isoformat(),
            "max_participants": 0,
        }
    await _advance_message(request, data, _next_step_after_draw_param(data))


async def _handle_participation_cost(request: WizardMessageRequest) -> None:
    data = {
        **request.data,
        "participation_cost": _parse_non_negative_int(request.text, "扣除积分"),
    }
    await _advance_message(request, data, _next_step_after_points(data))


def _ranking_mode(data: dict) -> bool:
    return data.get("selection_mode") == "ranking_random"


async def _handle_invite_requirement(request: WizardMessageRequest) -> None:
    if _ranking_mode(request.data):
        value = _parse_non_negative_int(request.text, "邀请入围最低人数")
    else:
        value = _parse_positive_int(request.text, "邀请人数")
    data = {**request.data, "required_invites": value}
    await _advance_message(request, data, "finalist_limit" if _ranking_mode(data) else "preset_confirm")


async def _handle_activity_requirement(request: WizardMessageRequest) -> None:
    if _ranking_mode(request.data):
        value = _parse_non_negative_int(request.text, "活跃入围最低消息数")
    else:
        value = _parse_positive_int(request.text, "活跃消息数")
    data = {**request.data, "required_activity_count": value}
    await _advance_message(request, data, "finalist_limit" if _ranking_mode(data) else "preset_confirm")


async def _handle_finalist_limit(request: WizardMessageRequest) -> None:
    data = {
        **request.data,
        "finalist_limit": _parse_positive_int(request.text, "入围人数"),
    }
    await _advance_message(request, data, "preset_confirm")


async def _handle_preset_winners(request: WizardMessageRequest) -> None:
    if request.text.strip() in PRESET_CLEAR_WORDS:
        data = {
            **request.data,
            "preset_winner_ids": [],
            "preset_winner_assignments": [],
        }
        await _advance_message(request, data, "preset_confirm")
        return
    prizes = list(request.data.get("prizes") or [])
    preset_ids, assignments = await _parse_preset_winner_refs_from_values(
        request.update,
        request.context,
        request.session,
        values=request.text.strip().splitlines() or [request.text],
        prizes=prizes,
        include_message_entities=True,
        resolve_username=request.resolve_username,
    )
    if len(preset_ids) > _prize_slot_count(prizes):
        raise ValueError("内定中奖人数不能超过中奖人数")
    data = {
        **request.data,
        "preset_winner_ids": preset_ids,
        "preset_winner_assignments": assignments,
    }
    await _advance_message(request, data, "preset_confirm")


MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "title": _handle_title,
    "subscribe_targets": _handle_subscribe_targets,
    "prize_name": _handle_prize_name,
    "prize_quantity": _handle_prize_quantity,
    "prize_action": _handle_button_only,
    "draw_param": _handle_draw_param,
    "point_type": _handle_button_only,
    "participation_cost": _handle_participation_cost,
    "invite_requirement": _handle_invite_requirement,
    "activity_requirement": _handle_activity_requirement,
    "finalist_limit": _handle_finalist_limit,
    "preset_winners": _handle_preset_winners,
}


async def _handle_lottery_wizard_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    state: object,
    text: str,
    resolve_username,
    validate_subscribe,
) -> None:
    data = _state_data(state)
    handler = MESSAGE_HANDLERS.get(str(data.get("step") or ""))
    if handler is None:
        await update.effective_message.reply_text("当前抽奖创建状态异常，请取消后重新创建。")
        return
    request = WizardMessageRequest(
        update,
        context,
        session,
        state,
        data,
        text,
        resolve_username,
        validate_subscribe,
    )
    try:
        await handler(request)
        await session.commit()
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}\n请重新输入，或使用 /cancel 取消。")
        await session.commit()
