from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.features.activity.services.lottery_service import get_lottery, get_lottery_participant_count, join_lottery
from backend.features.points.services.points_service import change_points, get_balance


class LotteryParticipationMixin:
    async def handle_join(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
    ) -> None:
        q = update.callback_query
        chat = update.effective_chat
        user = update.effective_user

        if chat.type == "private":
            await self.message_helper.safe_edit(update, "请在群里使用。")
            return

        db: Database = context.application.bot_data["db"]
        participant_count = 0
        error_msg = None

        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                error_msg = "抽奖不存在。"
            elif lottery.chat_id != chat.id:
                error_msg = "此抽奖不属于当前群组。"
            else:
                user_points = await get_balance(session, chat.id, user.id)
                stmt = select(ChatMember).where(ChatMember.chat_id == chat.id, ChatMember.user_id == user.id)
                result = await session.execute(stmt)
                member = result.scalar_one_or_none()
                member_joined_at = member.joined_at if member else None

                result = await join_lottery(
                    session,
                    lottery_id=lottery_id,
                    user_id=user.id,
                    points_balance=user_points,
                    member_joined_at=member_joined_at,
                )
                if not result.success:
                    error_messages = {
                        "already_joined": "你已经参与过此抽奖了",
                        "lottery_not_open": "抽奖尚未开始",
                        "lottery_closed": "抽奖已结束",
                        "lottery_completed": "抽奖已开奖",
                        "insufficient_points": f"积分不足，需要至少 {lottery.min_points} 积分",
                        "insufficient_invites": "邀请人数未达标，暂时不能参与该抽奖",
                        "insufficient_activity": "最近活跃消息数未达标，暂时不能参与该抽奖",
                        "ranking_auto_selection": "本玩法无需手动参与，系统会在开奖时按排行自动生成入围名单",
                        "max_participants_reached": "参与人数已满",
                        "not_member_long_enough": f"入群天数不足，需要 {lottery.requirement_days} 天以上",
                        "outside_join_time": "不在参与时间内",
                    }
                    error_msg = error_messages.get(result.reason, "无法参与抽奖")
                else:
                    if lottery.participation_cost > 0:
                        success, _ = await change_points(
                            session,
                            chat_id=chat.id,
                            user_id=user.id,
                            amount=-lottery.participation_cost,
                            txn_type=PointsTxnType.lottery_join.value,
                            reason=f"参与抽奖: {lottery.title}",
                        )
                        if not success:
                            error_msg = "积分不足，无法参与"
                            await session.rollback()

                if not error_msg:
                    participant_count = await get_lottery_participant_count(session, lottery_id)
                else:
                    await session.rollback()
            await session.commit()

        if error_msg:
            await q.answer(error_msg, show_alert=True)
        else:
            await q.answer(f"🎉 参与成功！当前人数: {participant_count}", show_alert=True)
