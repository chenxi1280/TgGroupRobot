from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
)
from backend.features.activity.services.lottery_winner_parsing import (
    validate_preset_winner_assignments,
    validate_unique_prize_names,
)
from backend.features.activity.services.lottery_subscription import (
    validate_lottery_subscribe_targets,
)

from backend.features.activity.lottery_creation_parsing import (
    _prize_slot_count,
)


from backend.features.activity.lottery_creation_views import (
    _activity_requirement_prompt as _activity_requirement_prompt,
    _append_lottery_wizard_guide as _append_lottery_wizard_guide,
    _create_parent_callback as _create_parent_callback,
    _deadline_prompt as _deadline_prompt,
    _finalist_limit_prompt as _finalist_limit_prompt,
    _format_lottery_wizard_summary as _format_lottery_wizard_summary,
    _full_participants_prompt as _full_participants_prompt,
    _invite_requirement_prompt as _invite_requirement_prompt,
    _is_private_admin_context as _is_private_admin_context,
    _lottery_draft_required_items as _lottery_draft_required_items,
    _lottery_title_prompt as _lottery_title_prompt,
    _participation_cost_prompt as _participation_cost_prompt,
    _point_type_keyboard as _point_type_keyboard,
    _preset_confirm_keyboard as _preset_confirm_keyboard,
    _prize_action_keyboard as _prize_action_keyboard,
    _prize_name_prompt as _prize_name_prompt,
    _prize_quantity_prompt as _prize_quantity_prompt,
    _subscribe_targets_prompt as _subscribe_targets_prompt,
    _wizard_back_callback as _wizard_back_callback,
    _wizard_nav_keyboard as _wizard_nav_keyboard,
)

def _state_data(state: object) -> dict:
    return dict(getattr(state, "state_data", None) or {})


def _save_state_data(state: object, data: dict) -> None:
    state.state_data = {
        **data,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


async def _commit_wizard_state_before_prompt(session) -> None:
    commit = getattr(session, "commit", None)
    if commit is not None:
        await commit()


def _draw_time_from_draft(data: dict) -> dt.datetime:
    raw = data.get("draw_time")
    if raw:
        parsed = dt.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3650)


@dataclass(frozen=True, slots=True)
class LotteryDraftValues:
    lottery_type: str
    selection_mode: str
    draw_trigger: str
    title: str
    prizes: list[dict]
    preset_winner_ids: list[int]
    preset_winner_assignments: list[dict]
    max_participants: int
    required_invites: int
    required_activity_count: int
    finalist_limit: int
    subscribe_targets: list[dict]


def _draft_text(data: dict, key: str, default: str = "") -> str:
    return str(data.get(key) or default)


def _draft_int(data: dict, key: str) -> int:
    return int(data.get(key) or 0)


def _draft_list(data: dict, key: str) -> list:
    return list(data.get(key) or [])


def _draft_values(data: dict) -> LotteryDraftValues:
    return LotteryDraftValues(
        lottery_type=_draft_text(data, "lottery_type", "common"),
        selection_mode=_draft_text(data, "selection_mode", "threshold_random"),
        draw_trigger=_draft_text(data, "draw_trigger", "time_deadline"),
        title=_draft_text(data, "title").strip(),
        prizes=_draft_list(data, "prizes"),
        preset_winner_ids=[int(user_id) for user_id in _draft_list(data, "preset_winner_ids")],
        preset_winner_assignments=_draft_list(data, "preset_winner_assignments"),
        max_participants=_draft_int(data, "max_participants"),
        required_invites=_draft_int(data, "required_invites"),
        required_activity_count=_draft_int(data, "required_activity_count"),
        finalist_limit=_draft_int(data, "finalist_limit"),
        subscribe_targets=_draft_list(data, "subscribe_targets"),
    )


def _validate_prizes(values: LotteryDraftValues) -> None:
    if not values.prizes:
        raise ValueError("至少需要设置一个奖品")
    validate_unique_prize_names(values.prizes)
    validate_preset_winner_assignments(values.preset_winner_assignments, values.prizes)
    if len(values.preset_winner_ids) > _prize_slot_count(values.prizes):
        raise ValueError("内定中奖人数不能超过中奖人数")


def _validate_draw(values: LotteryDraftValues, data: dict) -> None:
    if values.draw_trigger == "full_participants" and values.max_participants <= 0:
        raise ValueError("满人开奖必须设置满员人数")
    if values.draw_trigger == "time_deadline" and not data.get("draw_time"):
        raise ValueError("定时开奖必须设置开奖时间")


def _validate_requirements(values: LotteryDraftValues) -> None:
    threshold_mode = values.selection_mode == "threshold_random"
    if values.lottery_type == "invite" and threshold_mode and values.required_invites <= 0:
        raise ValueError("邀请抽奖必须设置邀请人数")
    if values.lottery_type == "activity" and threshold_mode and values.required_activity_count <= 0:
        raise ValueError("群活跃抽奖必须设置活跃消息数")
    if values.selection_mode == "ranking_random" and values.finalist_limit <= 0:
        raise ValueError("排名入围随机玩法必须设置入围人数")


def _validate_identity(values: LotteryDraftValues) -> None:
    if values.lottery_type == "subscribe" and not values.subscribe_targets:
        raise ValueError("强制订阅抽奖必须设置关注目标")
    if not values.title:
        raise ValueError("抽奖名称不能为空")


def _build_config_from_state(data: dict) -> ParsedLotteryConfig:
    values = _draft_values(data)
    _validate_prizes(values)
    _validate_draw(values, data)
    _validate_requirements(values)
    _validate_identity(values)
    return ParsedLotteryConfig(
        lottery_type=values.lottery_type,
        title=values.title,
        description=data.get("description") or None,
        draw_time=_draw_time_from_draft(data),
        draw_trigger=values.draw_trigger,
        min_points=0,
        participation_cost=int(data.get("participation_cost") or 0),
        max_participants=values.max_participants,
        requirement_days=0,
        qualification_window_days=int(data.get("qualification_window_days") or 7),
        required_invites=values.required_invites,
        required_activity_count=values.required_activity_count,
        finalist_limit=values.finalist_limit,
        selection_mode=values.selection_mode,
        preset_winner_ids=values.preset_winner_ids,
        prizes=values.prizes,
        point_type_id=data.get("point_type_id"),
        point_type_name=data.get("point_type_name"),
        subscribe_targets=values.subscribe_targets if values.lottery_type == "subscribe" else None,
        subscribe_check_mode="all",
        preset_winner_assignments=values.preset_winner_assignments,
    )


def _next_step_after_draw_param(data: dict) -> str:
    lottery_type = data.get("lottery_type")
    if lottery_type == "subscribe":
        return "subscribe_targets"
    if lottery_type == "points":
        return "point_type"
    if lottery_type == "invite":
        return "invite_requirement"
    if lottery_type == "activity":
        return "activity_requirement"
    if data.get("selection_mode") == "ranking_random":
        return "finalist_limit"
    return "preset_confirm"


def _next_step_after_points(data: dict) -> str:
    if data.get("lottery_type") == "invite":
        return "invite_requirement"
    if data.get("lottery_type") == "activity":
        return "activity_requirement"
    if data.get("selection_mode") == "ranking_random":
        return "finalist_limit"
    return "preset_confirm"


def _previous_lottery_wizard_step(data: dict) -> str | None:
    step = data.get("step")
    lottery_type = data.get("lottery_type")
    fixed_steps = {
        "subscribe_targets": "draw_param",
        "prize_name": "title",
        "prize_quantity": "prize_name",
        "prize_action": "prize_name",
        "draw_param": "prize_action",
        "point_type": "draw_param",
        "participation_cost": "point_type",
        "preset_winners": "preset_confirm",
    }
    if step in fixed_steps:
        return fixed_steps[step]
    if step in {"invite_requirement", "activity_requirement"}:
        return "draw_param"
    if step == "finalist_limit":
        return _previous_condition_step(lottery_type)
    if step == "preset_confirm":
        return _previous_confirmation_step(data)
    return None


def _previous_condition_step(lottery_type: str | None) -> str:
    return {
        "invite": "invite_requirement",
        "activity": "activity_requirement",
    }.get(lottery_type, "draw_param")


def _previous_confirmation_step(data: dict) -> str:
    if data.get("selection_mode") == "ranking_random":
        return "finalist_limit"
    return {
        "invite": "invite_requirement",
        "activity": "activity_requirement",
        "points": "participation_cost",
        "subscribe": "subscribe_targets",
    }.get(data.get("lottery_type"), "draw_param")


def _qualification_rules_from_config(config: ParsedLotteryConfig) -> dict:
    rules = {
        "draw_trigger": config.draw_trigger,
        "preset_winner_ids": config.preset_winner_ids,
        "window_days": config.qualification_window_days,
        "required_invites": config.required_invites,
        "required_activity_count": config.required_activity_count,
        "finalist_limit": config.finalist_limit,
        "selection_mode": config.selection_mode,
    }
    if config.preset_winner_assignments:
        rules["preset_winner_assignments"] = list(config.preset_winner_assignments)
    if config.point_type_id:
        rules["point_type_id"] = config.point_type_id
        rules["point_type_name"] = config.point_type_name
    if config.lottery_type == "subscribe":
        rules["requires_lottery_subscribe"] = True
        rules["subscribe_check_mode"] = config.subscribe_check_mode or "all"
        rules["subscribe_targets"] = list(config.subscribe_targets or [])
    return rules


async def _validate_lottery_publish_config(context: ContextTypes.DEFAULT_TYPE, config: ParsedLotteryConfig) -> None:
    if config.lottery_type != "subscribe":
        return
    config.subscribe_targets = await validate_lottery_subscribe_targets(context, list(config.subscribe_targets or []))
