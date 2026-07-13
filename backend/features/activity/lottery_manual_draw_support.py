from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_subscription import (
    filter_lottery_subscribed_user_ids,
    get_lottery_subscribe_targets,
    requires_lottery_subscribe,
)
from backend.platform.db.schema.models.core import TgUser
from backend.shared.callback_parser import CallbackParser
_MANUAL_DRAW_SELECT_PRIZE_CALLBACK_IMPL_THRESHOLD_6 = 6
_MANUAL_DRAW_SELECT_WINNER_CALLBACK_IMPL_THRESHOLD_7 = 7
_MANUAL_DRAW_WINNER_PAGE_CALLBACK_IMPL_THRESHOLD_6 = 6


@dataclass(frozen=True, slots=True)
class PrizeSelection:
    target_chat_id: int
    lottery_id: int
    prize_index: int
    prize_name: str | None = None
    winner_user_id: int | None = None
    page: int | None = None


def _parse_prize_selection(
    callback_data: str,
    *,
    mode: str,
) -> PrizeSelection | None:
    cb = CallbackParser.parse(callback_data)
    parsers = {
        "prize": _parse_prize_callback,
        "winner": _parse_winner_callback,
        "page": _parse_page_callback,
    }
    parser = parsers.get(mode)
    return parser(cb) if parser else None


def _base_selection(cb: CallbackParser) -> tuple[int, int, int] | None:
    values = (cb.get_int(2), cb.get_int(3), cb.get_int(4))
    if any(value is None for value in values):
        return None
    return values


def _parse_prize_callback(cb: CallbackParser) -> PrizeSelection | None:
    base = _base_selection(cb)
    prize_name = cb.get(5)
    if cb.length() < _MANUAL_DRAW_SELECT_PRIZE_CALLBACK_IMPL_THRESHOLD_6 or base is None or not prize_name:
        return None
    return PrizeSelection(*base, prize_name=prize_name)


def _parse_winner_callback(cb: CallbackParser) -> PrizeSelection | None:
    base = _base_selection(cb)
    winner_user_id = cb.get_int(5)
    prize_name = cb.get(6)
    if cb.length() < _MANUAL_DRAW_SELECT_WINNER_CALLBACK_IMPL_THRESHOLD_7:
        return None
    if base is None or winner_user_id is None or not prize_name:
        return None
    return PrizeSelection(*base, prize_name=prize_name, winner_user_id=winner_user_id)


def _parse_page_callback(cb: CallbackParser) -> PrizeSelection | None:
    base = _base_selection(cb)
    page = cb.get_int(5)
    if cb.length() < _MANUAL_DRAW_WINNER_PAGE_CALLBACK_IMPL_THRESHOLD_6 or base is None or page is None:
        return None
    return PrizeSelection(*base, page=page)


async def _eligible_participants(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    lottery,
    *,
    get_lottery_participants_fn,
) -> list:
    participants = await get_lottery_participants_fn(session, lottery.id)
    if requires_lottery_subscribe(lottery):
        rules = lottery.qualification_rules or {}
        eligible_user_ids = await filter_lottery_subscribed_user_ids(
            context,
            get_lottery_subscribe_targets(rules),
            {int(participant.user_id) for participant in participants},
            check_mode=rules.get("subscribe_check_mode") or "all",
        )
        participants = [
            participant
            for participant in participants
            if int(participant.user_id) in eligible_user_ids
        ]
    result = await session.execute(
        select(TgUser).where(TgUser.id.in_([item.user_id for item in participants]))
    )
    users = {user.id: user for user in result.scalars().all()}
    for participant in participants:
        participant.user_info = users.get(participant.user_id)
    return participants


async def _is_authorized(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    handler,
    *,
    target_chat_id: int,
    is_user_admin_fn,
) -> bool:
    allowed = await is_user_admin_fn(context, target_chat_id, update.effective_user.id)
    if not allowed:
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
    return allowed


def _winner_display_name(winner_user, winner_user_id: int) -> str:
    if winner_user is None:
        return "未知用户"
    return (
        winner_user.first_name
        or winner_user.last_name
        or winner_user.username
        or f"用户{winner_user_id}"
    )


def _prize_pool(prizes: list[dict]) -> list[str]:
    return [
        prize["name"]
        for prize in prizes
        for _ in range(prize.get("quantity", 1))
    ]


def _manual_completion_error(lottery, winners: dict) -> str | None:
    if not winners:
        return "请先为所有奖项选择中奖人。"
    if lottery.status != "pending":
        return "抽奖已开奖或已取消。"
    missing_count = len(_prize_pool(lottery.prizes)) - len(winners)
    if missing_count > 0:
        return f"还有 {missing_count} 个奖项未选择中奖人，请先完成选择。"
    return None


async def _invalid_subscribed_winners(
    context: ContextTypes.DEFAULT_TYPE,
    lottery,
    winner_user_ids: list[int],
) -> list[int]:
    if not requires_lottery_subscribe(lottery):
        return []
    rules = lottery.qualification_rules or {}
    eligible = await filter_lottery_subscribed_user_ids(
        context,
        get_lottery_subscribe_targets(rules),
        {int(user_id) for user_id in winner_user_ids},
        check_mode=rules.get("subscribe_check_mode") or "all",
    )
    return sorted(set(winner_user_ids) - eligible)


async def _create_manual_winners(
    session,
    lottery,
    winners: dict,
    *,
    create_lottery_winner_fn,
) -> list:
    created = []
    for prize_index, winner_info in winners.items():
        prize_index_int = int(prize_index)
        prize_config = lottery.prizes[prize_index_int // 10]
        winner = await create_lottery_winner_fn(
            session,
            lottery_id=lottery.id,
            user_id=winner_info["user_id"],
            prize_name=winner_info["prize_name"],
            prize_index=prize_index_int,
        )
        winner.points_reward = prize_config.get("points_reward", 0)
        created.append(winner)
    return created


@dataclass(frozen=True, slots=True)
class ManualCompletion:
    state: object
    winners: dict
    lottery: object


async def _load_manual_completion(
    session,
    *,
    chat_id: int,
    user_id: int,
    target_chat_id: int,
    lottery_id: int,
    get_user_state_fn,
    get_lottery_fn,
) -> tuple[ManualCompletion | None, str | None]:
    state = await get_user_state_fn(session, chat_id, user_id)
    if not state or state.state_type != "manual_draw":
        return None, "未找到开奖信息，请重新开始。"
    winners = state.state_data.get("winners", {})
    lottery = await get_lottery_fn(session, lottery_id)
    if not lottery or lottery.chat_id != target_chat_id:
        return None, "抽奖不存在。"
    error = _manual_completion_error(lottery, winners)
    if error:
        return None, error
    return ManualCompletion(state, winners, lottery), None


async def _winner_users(session, winner_user_ids: list[int]) -> dict:
    result = await session.execute(select(TgUser).where(TgUser.id.in_(winner_user_ids)))
    return {user.id: user for user in result.scalars().all()}


async def _finish_manual_draw(
    session,
    completion: ManualCompletion,
    *,
    chat_id: int,
    user_id: int,
    create_lottery_winner_fn,
    clear_user_state_fn,
    distribute_lottery_rewards_fn,
    generate_lottery_announcement_fn,
) -> str:
    winner_ids = [item["user_id"] for item in completion.winners.values()]
    users = await _winner_users(session, winner_ids)
    created = await _create_manual_winners(
        session,
        completion.lottery,
        completion.winners,
        create_lottery_winner_fn=create_lottery_winner_fn,
    )
    await distribute_lottery_rewards_fn(session, completion.lottery, created)
    completion.lottery.status = "completed"
    completion.lottery.drawn_at = dt.datetime.now(dt.UTC)
    announcement = generate_lottery_announcement_fn(completion.lottery, created, users)
    await clear_user_state_fn(session, chat_id, user_id)
    return announcement


async def _record_selected_winner(
    session,
    selection: PrizeSelection,
    *,
    chat_id: int,
    user_id: int,
    lottery,
    get_user_state_fn,
    set_user_state_fn,
) -> tuple[str, dict]:
    state = await get_user_state_fn(session, chat_id, user_id)
    if not state or state.state_type != "manual_draw":
        state = await set_user_state_fn(session, chat_id, user_id, "manual_draw", {})
    winners = dict(state.state_data.get("winners", {}))
    result = await session.execute(
        select(TgUser).where(TgUser.id == selection.winner_user_id)
    )
    winner_user = result.scalar_one_or_none()
    winner_name = _winner_display_name(winner_user, selection.winner_user_id)
    winners[str(selection.prize_index)] = {
        "user_id": selection.winner_user_id,
        "prize_name": selection.prize_name,
        "name": winner_name,
    }
    state.state_data = {
        **state.state_data,
        "winners": winners,
        "lottery_id": selection.lottery_id,
        "target_chat_id": lottery.chat_id,
    }
    return winner_name, winners


async def _complete_manual_draw(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    user_id: int,
    target_chat_id: int,
    lottery_id: int,
    get_user_state_fn,
    get_lottery_fn,
    create_lottery_winner_fn,
    clear_user_state_fn,
    distribute_lottery_rewards_fn,
    generate_lottery_announcement_fn,
) -> tuple[str | None, str | None]:
    completion, error = await _load_manual_completion(
        session,
        chat_id=chat_id,
        user_id=user_id,
        target_chat_id=target_chat_id,
        lottery_id=lottery_id,
        get_user_state_fn=get_user_state_fn,
        get_lottery_fn=get_lottery_fn,
    )
    if error:
        return None, error
    winner_ids = [item["user_id"] for item in completion.winners.values()]
    invalid_ids = await _invalid_subscribed_winners(context, completion.lottery, winner_ids)
    if invalid_ids:
        return None, "有已选择的中奖人当前未满足本抽奖订阅条件，请返回重新选择。"
    announcement = await _finish_manual_draw(
        session,
        completion,
        chat_id=chat_id,
        user_id=user_id,
        create_lottery_winner_fn=create_lottery_winner_fn,
        clear_user_state_fn=clear_user_state_fn,
        distribute_lottery_rewards_fn=distribute_lottery_rewards_fn,
        generate_lottery_announcement_fn=generate_lottery_announcement_fn,
    )
    return announcement, None


async def _load_manual_menu(
    session,
    *,
    chat_id: int,
    user_id: int,
    target_chat_id: int,
    lottery_id: int,
    get_user_state_fn,
    get_lottery_fn,
) -> tuple[object | None, dict, str | None]:
    state = await get_user_state_fn(session, chat_id, user_id)
    winners = state.state_data.get("winners", {}) if state else {}
    lottery = await get_lottery_fn(session, lottery_id)
    if not lottery or lottery.chat_id != target_chat_id:
        return None, winners, "抽奖不存在。"
    return lottery, winners, None
