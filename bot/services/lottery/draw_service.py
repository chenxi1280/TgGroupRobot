"""抽奖开奖服务 - 处理随机开奖和奖励发放"""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import Lottery, LotteryParticipant, LotteryWinner, TgUser
from bot.services.lottery.manager_service import get_lottery_participants


async def create_lottery_winner(
    session: AsyncSession,
    lottery_id: int,
    user_id: int,
    prize_name: str,
    prize_index: int,
    points_reward: int = 0,
) -> LotteryWinner:
    """
    创建中奖记录

    Args:
        session: 数据库会话
        lottery_id: 抽奖ID
        user_id: 用户ID
        prize_name: 奖品名称
        prize_index: 奖品索引
        points_reward: 积分奖励

    Returns:
        创建的中奖记录对象
    """
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


async def perform_random_draw(
    session: AsyncSession,
    lottery: Lottery,
) -> list[LotteryWinner]:
    """
    执行随机开奖

    Args:
        session: 数据库会话
        lottery: 抽奖对象

    Returns:
        中奖者列表
    """
    # 获取所有参与者
    participants = await get_lottery_participants(session, lottery.id)
    if not participants:
        return []

    # 获取用户信息
    user_ids = [p.user_id for p in participants]
    stmt = select(TgUser).where(TgUser.id.in_(user_ids))
    result = await session.execute(stmt)
    users = {u.id: u for u in result.scalars().all()}

    # 构建奖品列表（展开数量）
    prize_list = []
    for prize in lottery.prizes:
        quantity = prize.get("quantity", 1)
        for _ in range(quantity):
            prize_list.append({
                "prize_index": len(prize_list),
                "name": prize["name"],
                "points_reward": prize.get("points_reward", 0),
            })

    if not prize_list:
        return []

    # 随机选择中奖者
    winners = []
    available_participants = participants.copy()
    random.shuffle(available_participants)

    for prize in prize_list:
        if not available_participants:
            break

        participant = available_participants.pop()
        user = users.get(participant.user_id)

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


def generate_lottery_announcement(
    lottery: Lottery,
    winners: list[LotteryWinner],
    users: dict[int, TgUser],
) -> str:
    """
    生成开奖公告（含@中奖用户）

    Args:
        lottery: 抽奖对象
        winners: 中奖者列表
        users: 用户信息字典

    Returns:
        开奖公告文本
    """
    text = f"🎉 抽奖【{lottery.title}】开奖结果\n\n"
    text += f"🎁 中奖名单：\n"

    for winner in winners:
        user = users.get(winner.user_id)
        if user:
            # 使用 mention 格式 @用户
            mention = f"[{user.full_name or user.username or '用户'}](tg://user?id={winner.user_id})"
            text += f"• {winner.prize_name}: {mention}"
            if winner.points_reward > 0:
                text += f" （+{winner.points_reward}积分）"
            text += "\n"
        else:
            text += f"• {winner.prize_name}: 用户{winner.user_id}\n"

    return text


async def distribute_lottery_rewards(
    session: AsyncSession,
    lottery: Lottery,
    winners: list[LotteryWinner],
) -> None:
    """
    发放中奖积分奖励

    Args:
        session: 数据库会话
        lottery: 抽奖对象
        winners: 中奖者列表
    """
    from bot.services.points.account_service import change_points

    for winner in winners:
        if winner.points_reward > 0:
            # 发放积分
            await change_points(
                session,
                lottery.chat_id,
                winner.user_id,
                winner.points_reward,
                "lottery_reward",
                f"抽奖【{lottery.title}】中奖奖励"
            )
