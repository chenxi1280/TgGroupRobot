from __future__ import annotations

import datetime as dt
import html
import random

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.lottery_service_parsing import lottery_type_label
from backend.features.activity.services.lottery_service_queries import get_lottery_participants
from backend.platform.db.schema.models.core import Lottery, LotteryParticipant, LotteryWinner, TgUser
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import EngagementChatStat
from backend.platform.db.schema.models.core import InviteTracking
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)


def _build_prize_slots(prizes: list[dict]) -> list[dict]:
    prize_list = []
    for prize in prizes:
        for _ in range(prize.get("quantity", 1)):
            prize_list.append(
                {
                    "prize_index": len(prize_list),
                    "name": prize["name"],
                    "points_reward": prize.get("points_reward", 0),
                }
            )
    return prize_list


def _pop_prize_slot_by_name(prize_list: list[dict], prize_name: str) -> dict | None:
    for index, prize in enumerate(prize_list):
        if str(prize.get("name") or "") == prize_name:
            return prize_list.pop(index)
    return None


async def build_ranked_finalists(session: AsyncSession, lottery: Lottery) -> list[LotteryParticipant]:
    qualification_rules = lottery.qualification_rules or {}
    finalist_limit = max(int(qualification_rules.get("finalist_limit") or 0), 0)
    window_days = max(int(qualification_rules.get("window_days") or 0), 0)
    required_invites = max(int(qualification_rules.get("required_invites") or 0), 0)
    required_activity = max(int(qualification_rules.get("required_activity_count") or 0), 0)
    if finalist_limit <= 0:
        return []

    user_ids = await _ranked_finalist_user_ids(
        session,
        lottery,
        finalist_limit=finalist_limit,
        window_days=window_days,
        required_invites=required_invites,
        required_activity=required_activity,
    )
    return [LotteryParticipant(lottery_id=lottery.id, user_id=user_id, points_balance=0) for user_id in user_ids]


async def _ranked_finalist_user_ids(
    session,
    lottery,
    *,
    finalist_limit: int,
    window_days: int,
    required_invites: int,
    required_activity: int,
) -> list[int]:
    now = dt.datetime.now(dt.timezone.utc)
    if lottery.lottery_type == "invite":
        return await _ranked_invite_user_ids(
            session, lottery, now=now, finalist_limit=finalist_limit,
            window_days=window_days, required_invites=required_invites,
        )
    if lottery.lottery_type != "activity":
        return []
    return await _ranked_activity_user_ids(
        session, lottery, now=now, finalist_limit=finalist_limit,
        window_days=window_days, required_activity=required_activity,
    )


async def _ranked_invite_user_ids(session, lottery, *, now, finalist_limit: int, window_days: int, required_invites: int) -> list[int]:
    stmt = select(InviteTracking.inviter_user_id, func.count(InviteTracking.id).label("cnt")).where(
        InviteTracking.chat_id == lottery.chat_id, InviteTracking.inviter_user_id.is_not(None)
    ).group_by(InviteTracking.inviter_user_id).order_by(
        func.count(InviteTracking.id).desc(), InviteTracking.inviter_user_id.asc()
    ).limit(finalist_limit)
    if window_days > 0:
        stmt = stmt.where(InviteTracking.joined_at >= now - dt.timedelta(days=window_days))
    rows = (await session.execute(stmt)).all()
    return [int(row[0]) for row in rows if row[0] is not None and int(row[1] or 0) >= required_invites]


async def _ranked_activity_user_ids(session, lottery, *, now, finalist_limit: int, window_days: int, required_activity: int) -> list[int]:
    stmt = select(
        EngagementChatStat.user_id, func.coalesce(func.sum(EngagementChatStat.message_count), 0).label("cnt")
    ).where(EngagementChatStat.chat_id == lottery.chat_id).group_by(EngagementChatStat.user_id).order_by(
        func.sum(EngagementChatStat.message_count).desc(), EngagementChatStat.user_id.asc()
    ).limit(finalist_limit)
    if window_days > 0:
        stmt = stmt.where(EngagementChatStat.biz_date >= (now - dt.timedelta(days=window_days)).date())
    rows = (await session.execute(stmt)).all()
    return [int(row[0]) for row in rows if int(row[1] or 0) >= required_activity]


async def create_lottery_winner(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    *, prize_name: str,
    prize_index: int,
    points_reward: int = 0,
) -> LotteryWinner:
    winner = LotteryWinner(
        lottery_id=lottery_id,
        user_id=user_id,
        prize_name=prize_name,
        prize_index=prize_index,
        points_reward=points_reward,
    )
    session.add(winner)
    await session.flush()
    return winner


def _valid_preset_winner_ids(rules: dict, eligible_user_ids: set[int] | None) -> list[int]:
    winner_ids: list[int] = []
    for raw_user_id in rules.get("preset_winner_ids") or rules.get("fixed_winner_ids") or []:
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in winner_ids:
            continue
        if eligible_user_ids is None or user_id in eligible_user_ids:
            winner_ids.append(user_id)
    return winner_ids


async def _new_lottery_winner(session, lottery: Lottery, user_id: int, *, prize: dict) -> LotteryWinner:
    from backend.shared.services.user_service import ensure_user

    await ensure_user(session, user_id, None, first_name=None, last_name=None, language_code=None)
    winner = LotteryWinner(
        lottery_id=lottery.id,
        user_id=user_id,
        prize_name=prize["name"],
        prize_index=prize["prize_index"],
        points_reward=prize["points_reward"],
    )
    session.add(winner)
    return winner


async def _assign_named_preset_winners(
    session,
    lottery,
    assignments,
    *,
    prizes: list[dict],
    eligible_user_ids: set[int] | None,
) -> tuple[list[LotteryWinner], list[dict], set[int]]:
    remaining = list(prizes)
    winners: list[LotteryWinner] = []
    used: set[int] = set()
    for item in assignments:
        try:
            user_id = int(item.get("user_id"))
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in used or (eligible_user_ids is not None and user_id not in eligible_user_ids):
            continue
        prize = _pop_prize_slot_by_name(remaining, str(item.get("prize_name") or "").strip())
        if prize is None:
            continue
        winners.append(await _new_lottery_winner(session, lottery, user_id, prize=prize))
        used.add(user_id)
    return winners, remaining, used


async def _assign_ordered_preset_winners(
    session,
    lottery,
    preset_ids,
    *,
    prizes: list[dict],
    used_user_ids: set[int],
) -> tuple[list[LotteryWinner], list[dict], set[int]]:
    remaining = list(prizes)
    used = set(used_user_ids)
    winners: list[LotteryWinner] = []
    for user_id in preset_ids:
        if not remaining:
            break
        if user_id in used:
            continue
        winners.append(await _new_lottery_winner(session, lottery, user_id, prize=remaining.pop(0)))
        used.add(user_id)
    return winners, remaining, used


def _assign_random_lottery_winners(session, lottery, participants, *, prizes: list[dict], used_user_ids: set[int]) -> list[LotteryWinner]:
    available = [participant for participant in participants if participant.user_id not in used_user_ids]
    random.shuffle(available)
    winners: list[LotteryWinner] = []
    for prize in prizes:
        if not available:
            break
        participant = available.pop()
        winner = LotteryWinner(
            lottery_id=lottery.id, user_id=participant.user_id, prize_name=prize["name"],
            prize_index=prize["prize_index"], points_reward=prize["points_reward"],
        )
        session.add(winner)
        winners.append(winner)
    return winners


async def _draw_eligible_participants(session, lottery, *, rules: dict, eligible_user_ids: set[int] | None):
    participants = await get_lottery_participants(session, lottery.id)
    if rules.get("selection_mode") == "ranking_random" and lottery.lottery_type in {"invite", "activity"}:
        participants = await build_ranked_finalists(session, lottery)
    if eligible_user_ids is None:
        return participants
    return [participant for participant in participants if int(participant.user_id) in eligible_user_ids]


async def perform_random_draw(
    session: AsyncSession,
    lottery: Lottery,
    *,
    eligible_user_ids: set[int] | None = None,
) -> list[LotteryWinner]:
    qualification_rules = lottery.qualification_rules or {}
    participants = await _draw_eligible_participants(
        session, lottery, rules=qualification_rules, eligible_user_ids=eligible_user_ids
    )

    prize_list = _build_prize_slots(lottery.prizes or [])
    preset_winner_ids = _valid_preset_winner_ids(qualification_rules, eligible_user_ids)
    if not prize_list:
        return []
    if not participants and not preset_winner_ids:
        return []

    preset_winner_assignments = qualification_rules.get("preset_winner_assignments") or []
    winners, remaining_prizes, used_user_ids = await _assign_named_preset_winners(
        session, lottery, preset_winner_assignments, prizes=prize_list, eligible_user_ids=eligible_user_ids
    )
    ordered, remaining_prizes, used_user_ids = await _assign_ordered_preset_winners(
        session, lottery, preset_winner_ids, prizes=remaining_prizes, used_user_ids=used_user_ids
    )
    winners.extend(ordered)
    winners.extend(_assign_random_lottery_winners(
        session, lottery, participants, prizes=remaining_prizes, used_user_ids=used_user_ids
    ))
    await session.flush()
    return winners


def generate_lottery_announcement(lottery: Lottery, winners: list[LotteryWinner], users: dict[int, TgUser]) -> str:
    text = f"🎉 {html.escape(lottery_type_label(lottery.lottery_type))}【{html.escape(lottery.title)}】开奖结果\n\n"
    text += "🎁 中奖名单：\n"
    for winner in winners:
        user = users.get(winner.user_id)
        prize_name = html.escape(winner.prize_name)
        if user:
            label = html.escape(format_user_display_name(user, winner.user_id))
            mention = f'<a href="tg://user?id={winner.user_id}">{label}</a>'
            text += f"• {prize_name}: {mention}"
            if winner.points_reward > 0:
                text += f" （+{winner.points_reward}积分）"
            text += "\n"
        else:
            mention = f'<a href="tg://user?id={winner.user_id}">用户{winner.user_id}</a>'
            text += f"• {prize_name}: {mention}\n"
    return text


async def distribute_lottery_rewards(session: AsyncSession, lottery: Lottery, winners: list[LotteryWinner]) -> None:
    from backend.features.points.services.points_service import change_points

    for winner in winners:
        if winner.points_reward > 0:
            success, _new_balance = await change_points(
                session,
                lottery.chat_id,
                winner.user_id,
                amount=winner.points_reward,
                txn_type=PointsTxnType.lottery_win.value,
                reason=f"抽奖【{lottery.title}】中奖奖励",
            )
            if not success:
                log.error(
                    "lottery_reward_failed",
                    lottery_id=lottery.id,
                    winner_id=winner.user_id,
                    reward_amount=winner.points_reward,
                )
