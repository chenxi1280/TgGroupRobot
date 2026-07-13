from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from telegram import InlineKeyboardMarkup, Update

from backend.features.activity.lottery_creation_config import (
    _activity_requirement_prompt,
    _append_lottery_wizard_guide,
    _build_config_from_state,
    _commit_wizard_state_before_prompt,
    _create_parent_callback,
    _deadline_prompt,
    _finalist_limit_prompt,
    _format_lottery_wizard_summary,
    _full_participants_prompt,
    _invite_requirement_prompt,
    _is_private_admin_context,
    _lottery_title_prompt,
    _participation_cost_prompt,
    _point_type_keyboard,
    _preset_confirm_keyboard,
    _prize_action_keyboard,
    _prize_name_prompt,
    _prize_quantity_prompt,
    _save_state_data,
    _subscribe_targets_prompt,
    _wizard_back_callback,
    _wizard_nav_keyboard,
)


async def _reply_point_type_prompt(update: Update, session, state: object, *, data: dict) -> None:
    from backend.features.points.services.points_extended_service import PointsExtendedService

    next_data = {**data, "step": "point_type"}
    _save_state_data(state, next_data)
    custom_types = await PointsExtendedService.list_custom_point_types(session, int(next_data["target_chat_id"]))
    await _commit_wizard_state_before_prompt(session)
    await update.effective_message.reply_text(
        _append_lottery_wizard_guide("请选择本次积分抽奖扣除哪一种积分。", next_data, next_step="选择积分类型后填写参与扣分"),
        reply_markup=_point_type_keyboard(int(next_data["target_chat_id"]), custom_types),
    )


async def _reply_preset_confirm(update: Update, session, state: object, *, data: dict) -> None:
    next_data = {**data, "step": "preset_confirm"}
    _save_state_data(state, next_data)
    config = _build_config_from_state(next_data)
    include_sensitive = _is_private_admin_context(update)
    await _commit_wizard_state_before_prompt(session)
    await update.effective_message.reply_text(
        _format_lottery_wizard_summary(config, include_sensitive=include_sensitive),
        reply_markup=_preset_confirm_keyboard(
            int(next_data["target_chat_id"]),
            bool(config.preset_winner_ids),
            include_sensitive=include_sensitive,
        ),
    )


@dataclass(frozen=True, slots=True)
class PromptSpec:
    text: str
    reply_markup: InlineKeyboardMarkup
    parse_mode: str | None = None


@dataclass(frozen=True, slots=True)
class PromptRequest:
    data: dict
    target_chat_id: int
    nav_keyboard: InlineKeyboardMarkup


PromptBuilder = Callable[[PromptRequest], PromptSpec]


def _guided_spec(
    request: PromptRequest,
    prompt: str,
    *,
    next_step: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> PromptSpec:
    return PromptSpec(
        _append_lottery_wizard_guide(prompt, request.data, next_step=next_step),
        reply_markup or request.nav_keyboard,
        parse_mode,
    )


def _title_spec(request: PromptRequest) -> PromptSpec:
    data = request.data
    prompt = _lottery_title_prompt(
        data.get("lottery_type", "common"),
        data.get("selection_mode", "threshold_random"),
        data.get("draw_trigger", "time_deadline"),
    )
    parent_callback = _create_parent_callback(
        request.target_chat_id,
        data.get("lottery_type", "common"),
        data.get("selection_mode", "threshold_random"),
    )
    keyboard = _wizard_nav_keyboard(request.target_chat_id, back_callback=parent_callback)
    return _guided_spec(request, prompt, next_step="填写抽奖名称", reply_markup=keyboard)


def _subscribe_spec(request: PromptRequest) -> PromptSpec:
    return _guided_spec(request, _subscribe_targets_prompt(), next_step="确认配置并发布")


def _prize_name_spec(request: PromptRequest) -> PromptSpec:
    return _guided_spec(request, _prize_name_prompt("1USDT"), next_step="填写中奖人数/份数")


def _prize_quantity_spec(request: PromptRequest) -> PromptSpec:
    prize_name = request.data.get("pending_prize_name") or "当前奖品"
    return _guided_spec(
        request,
        _prize_quantity_prompt(prize_name),
        next_step="继续添加奖品或完成奖品设置",
    )


def _prize_action_text(data: dict) -> str:
    prize_lines = [f"• {prize['name']} × {prize['quantity']}" for prize in data.get("prizes") or []]
    return (
        "当前奖品：\n"
        + ("\n".join(prize_lines) if prize_lines else "暂无")
        + "\n\n如果还有别的奖品，点击“添加下一个奖品”。\n"
        + "如果奖品已全部录入，点击“奖品设置完成”。\n"
        + "这里不用发送文字。"
    )


def _prize_action_spec(request: PromptRequest) -> PromptSpec:
    return _guided_spec(
        request,
        _prize_action_text(request.data),
        next_step="完成奖品后填写开奖条件",
        reply_markup=_prize_action_keyboard(request.target_chat_id),
    )


def _draw_spec(request: PromptRequest) -> PromptSpec:
    if request.data.get("draw_trigger") == "full_participants":
        return _guided_spec(request, _full_participants_prompt(), next_step="填写玩法门槛或确认发布")
    return _guided_spec(
        request,
        _deadline_prompt(),
        next_step="填写玩法门槛或确认发布",
        parse_mode="HTML",
    )


def _participation_spec(request: PromptRequest) -> PromptSpec:
    point_name = request.data.get("point_type_name") or "积分"
    return _guided_spec(
        request,
        _participation_cost_prompt(point_name),
        next_step="填写玩法门槛或确认发布",
    )


def _requirement_next_label(data: dict) -> str:
    return "填写入围人数" if data.get("selection_mode") == "ranking_random" else "确认配置并发布"


def _invite_spec(request: PromptRequest) -> PromptSpec:
    prompt = _invite_requirement_prompt(request.data.get("selection_mode"))
    return _guided_spec(request, prompt, next_step=_requirement_next_label(request.data))


def _activity_spec(request: PromptRequest) -> PromptSpec:
    prompt = _activity_requirement_prompt(request.data.get("selection_mode"))
    return _guided_spec(request, prompt, next_step=_requirement_next_label(request.data))


def _finalist_spec(request: PromptRequest) -> PromptSpec:
    return _guided_spec(request, _finalist_limit_prompt(), next_step="确认配置并发布")


PROMPT_BUILDERS: dict[str, PromptBuilder] = {
    "title": _title_spec,
    "subscribe_targets": _subscribe_spec,
    "prize_name": _prize_name_spec,
    "prize_quantity": _prize_quantity_spec,
    "prize_action": _prize_action_spec,
    "draw_param": _draw_spec,
    "participation_cost": _participation_spec,
    "invite_requirement": _invite_spec,
    "activity_requirement": _activity_spec,
    "finalist_limit": _finalist_spec,
}


def _prompt_request(data: dict) -> PromptRequest:
    target_chat_id = int(data["target_chat_id"])
    nav_keyboard = _wizard_nav_keyboard(
        target_chat_id,
        back_callback=_wizard_back_callback(target_chat_id),
    )
    return PromptRequest(data, target_chat_id, nav_keyboard)


async def _send_prompt(update: Update, spec: PromptSpec) -> None:
    await update.effective_message.reply_text(
        spec.text,
        reply_markup=spec.reply_markup,
        parse_mode=spec.parse_mode,
    )


async def _reply_next_prompt(update: Update, session, state: object, *, data: dict, next_step: str) -> None:
    next_data = {**data, "step": next_step}
    _save_state_data(state, next_data)
    if next_step == "point_type":
        await _reply_point_type_prompt(update, session, state, data=next_data)
        return
    if next_step == "preset_confirm":
        await _reply_preset_confirm(update, session, state, data=next_data)
        return
    await _commit_wizard_state_before_prompt(session)
    builder = PROMPT_BUILDERS.get(next_step)
    if builder is None:
        raise ValueError(f"不支持的抽奖创建步骤：{next_step}")
    await _send_prompt(update, builder(_prompt_request(next_data)))


async def _point_type_spec(session, request: PromptRequest) -> PromptSpec:
    from backend.features.points.services.points_extended_service import PointsExtendedService

    custom_types = await PointsExtendedService.list_custom_point_types(
        session,
        request.target_chat_id,
    )
    return _guided_spec(
        request,
        "请选择本次积分抽奖扣除哪一种积分。",
        next_step="选择积分类型后填写参与扣分",
        reply_markup=_point_type_keyboard(request.target_chat_id, custom_types),
    )


def _preset_spec(update: Update, request: PromptRequest) -> PromptSpec:
    config = _build_config_from_state(request.data)
    include_sensitive = _is_private_admin_context(update)
    keyboard = _preset_confirm_keyboard(
        request.target_chat_id,
        bool(config.preset_winner_ids),
        include_sensitive=include_sensitive,
    )
    return PromptSpec(
        _format_lottery_wizard_summary(config, include_sensitive=include_sensitive),
        keyboard,
    )


async def _edit_prompt(query, spec: PromptSpec) -> None:
    await query.edit_message_text(
        spec.text,
        reply_markup=spec.reply_markup,
        parse_mode=spec.parse_mode,
    )


async def _edit_wizard_step_prompt(
    update: Update,
    query,
    session,
    *,
    state: object,
    data: dict,
    step: str,
) -> None:
    data["step"] = step
    _save_state_data(state, data)
    request = _prompt_request(data)
    if step == "point_type":
        spec = await _point_type_spec(session, request)
    elif step == "preset_confirm":
        spec = _preset_spec(update, request)
    else:
        builder = PROMPT_BUILDERS.get(step)
        if builder is None:
            raise ValueError(f"不支持的抽奖创建步骤：{step}")
        spec = builder(request)
    await _edit_prompt(query, spec)

