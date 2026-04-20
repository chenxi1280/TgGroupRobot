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


async def build_ranked_finalists(session: AsyncSession, lottery: Lottery) -> list[LotteryParticipant]:
    qualification_rules = lottery.qualification_rules or {}
    finalist_limit = max(int(qualification_rules.get("finalist_limit") or 0), 0)
    window_days = max(int(qualification_rules.get("window_days") or 0), 0)
    required_invites = max(int(qualification_rules.get("required_invites") or 0), 0)
    required_activity = max(int(qualification_rules.get("required_activity_count") or 0), 0)
    if finalist_limit <= 0:
        return []

    now = dt.datetime.now(dt.timezone.utc)
    user_ids: list[int] = []
    if lottery.lottery_type == "invite":
        stmt = (
            select(InviteTracking.inviter_user_id, func.count(InviteTracking.id).label("cnt"))
            .where(InviteTracking.chat_id == lottery.chat_id, InviteTracking.inviter_user_id.is_not(None))
            .group_by(InviteTracking.inviter_user_id)
            .order_by(func.count(InviteTracking.id).desc(), InviteTracking.inviter_user_id.asc())
            .limit(finalist_limit)
        )
        if window_days > 0:
            stmt = stmt.where(InviteTracking.joined_at >= now - dt.timedelta(days=window_days))
        result = await session.execute(stmt)
        user_ids = [int(row[0]) for row in result.all() if row[0] is not None and int(row[1] or 0) >= required_invites]
    elif lottery.lottery_type == "activity":
        stmt = (
            select(EngagementChatStat.user_id, func.coalesce(func.sum(EngagementChatStat.message_count), 0).label("cnt"))
            .where(EngagementChatStat.chat_id == lottery.chat_id)
            .group_by(EngagementChatStat.user_id)
            .order_by(func.sum(EngagementChatStat.message_count).desc(), EngagementChatStat.user_id.asc())
            .limit(finalist_limit)
        )
        if window_days > 0:
            stmt = stmt.where(EngagementChatStat.biz_date >= (now - dt.timedelta(days=window_days)).date())
        result = await session.execute(stmt)
        user_ids = [int(row[0]) for row in result.all() if int(row[1] or 0) >= required_activity]

    finalists: list[LotteryParticipant] = []
    for user_id in user_ids:
        finalists.append(LotteryParticipant(lottery_id=lottery.id, user_id=user_id, points_balance=0))
    return finalists


async def create_lottery_winner(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    prize_name: str,
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


async def perform_random_draw(session: AsyncSession, lottery: Lottery) -> list[LotteryWinner]:
    participants = await get_lottery_participants(session, lottery.id)
    qualification_rules = lottery.qualification_rules or {}
    if qualification_rules.get("selection_mode") == "ranking_random" and lottery.lottery_type in {"invite", "activity"}:
        participants = await build_ranked_finalists(session, lottery)

    prize_list = _build_prize_slots(lottery.prizes or [])
    preset_winner_ids = []
    for user_id in qualification_rules.get("preset_winner_ids") or qualification_rules.get("fixed_winner_ids") or []:
        try:
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            continue
        if user_id_int > 0 and user_id_int not in preset_winner_ids:
            preset_winner_ids.append(user_id_int)
    if not prize_list:
        return []
    if not participants and not preset_winner_ids:
        return []

    winners = []
    used_user_ids: set[int] = set()
    remaining_prizes = prize_list.copy()
    if preset_winner_ids:
        from backend.shared.services.user_service import ensure_user

        for user_id in preset_winner_ids:
            if not remaining_prizes:
                break
            prize = remaining_prizes.pop(0)
            await ensure_user(session, user_id, None, None, None, None)
            winner = LotteryWinner(
                lottery_id=lottery.id,
                user_id=user_id,
                prize_name=prize["name"],
                prize_index=prize["prize_index"],
                points_reward=prize["points_reward"],
            )
            session.add(winner)
            winners.append(winner)
            used_user_ids.add(user_id)

    available_participants = participants.copy()
    available_participants = [p for p in available_participants if p.user_id not in used_user_ids]
    random.shuffle(available_participants)
    for prize in remaining_prizes:
        if not available_participants:
            break
        participant = available_participants.pop()
        winner = LotteryWinner(
            lottery_id=lottery.id,
            user_id=participant.user_id,
            prize_name=prize["name"],
            prize_index=prize["prize_index"],
            points_reward=prize["points_reward"],
        )
        session.add(winner)
        winners.append(winner)
    await session.flush()
    return winners


def generate_lottery_announcement(lottery: Lottery, winners: list[LotteryWinner], users: dict[int, TgUser]) -> str:
    text = f"🎉 {html.escape(lottery_type_label(lottery.lottery_type))}【{html.escape(lottery.title)}】开奖结果\n\n"
    text += "🎁 中奖名单：\n"
    for winner in winners:
        user = users.get(winner.user_id)
        prize_name = html.escape(winner.prize_name)
        if user:
            label = html.escape(user.full_name or user.username or "用户")
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
                winner.points_reward,
                PointsTxnType.lottery_win.value,
                f"抽奖【{lottery.title}】中奖奖励",
            )
            if not success:
                log.error(
                    "lottery_reward_failed",
                    lottery_id=lottery.id,
                    winner_id=winner.user_id,
                    reward_amount=winner.points_reward,
                )
