from __future__ import annotations

import datetime as dt

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember, TgUser
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.features.activity.services.lottery_service import get_lottery, get_lottery_participant_count, join_lottery
from backend.features.points.services.points_service import change_points, get_balance
from backend.features.points.services.points_extended_service import PointsExtendedService

log = structlog.get_logger(__name__)


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
        draw_announcement = None
        result_pin_enabled = False
        result_chat_id = None
        result_message_id = None

        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                error_msg = "抽奖不存在。"
            elif lottery.chat_id != chat.id:
                error_msg = "此抽奖不属于当前群组。"
            else:
                rules = lottery.qualification_rules or {}
                point_type_id = rules.get("point_type_id")
                point_type_name = rules.get("point_type_name") or "积分"
                if point_type_id:
                    user_points = await PointsExtendedService.get_custom_point_balance(
                        session,
                        chat_id=chat.id,
                        type_id=int(point_type_id),
                        user_id=user.id,
                    )
                else:
                    user_points = await get_balance(session, chat.id, user.id)
                    point_type_name = "积分"
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
                        "insufficient_points": f"{point_type_name}不足，需要至少 {(lottery.min_points or 0) + (lottery.participation_cost or 0)} {point_type_name}",
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
                        if point_type_id:
                            current_balance = await PointsExtendedService.get_custom_point_balance(
                                session,
                                chat_id=chat.id,
                                type_id=int(point_type_id),
                                user_id=user.id,
                            )
                            if current_balance < lottery.participation_cost:
                                error_msg = f"{point_type_name}不足，无法参与"
                                await session.rollback()
                            else:
                                await PointsExtendedService.adjust_custom_points(
                                    session,
                                    chat_id=chat.id,
                                    type_id=int(point_type_id),
                                    user_id=user.id,
                                    delta=-lottery.participation_cost,
                                    operator_user_id=None,
                                    reason_note=f"参与抽奖: {lottery.title}",
                                )
                        else:
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
                    rules = lottery.qualification_rules or {}
                    if (
                        rules.get("draw_trigger") == "full_participants"
                        and lottery.max_participants > 0
                        and participant_count >= lottery.max_participants
                    ):
                        from backend.features.activity.services.lottery_service import (
                            distribute_lottery_rewards,
                            generate_lottery_announcement,
                            get_or_create_lottery_setting,
                            perform_random_draw,
                        )

                        winners = await perform_random_draw(session, lottery)
                        if winners:
                            user_ids = [winner.user_id for winner in winners]
                            user_stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                            user_result = await session.execute(user_stmt)
                            users = {user.id: user for user in user_result.scalars().all()}
                            await distribute_lottery_rewards(session, lottery, winners)
                            setting = await get_or_create_lottery_setting(session, lottery.chat_id)
                            draw_announcement = generate_lottery_announcement(lottery, winners, users)
                            result_pin_enabled = setting.result_pin_enabled
                            result_chat_id = lottery.chat_id
                            try:
                                sent = await context.bot.send_message(
                                    chat_id=result_chat_id,
                                    text=draw_announcement,
                                    parse_mode="HTML",
                                )
                                result_message_id = sent.message_id
                            except Exception as exc:
                                log.error("full_participant_lottery_announcement_failed", lottery_id=lottery_id, error=str(exc))
                                error_msg = "已满员，但开奖结果公告发送失败，请稍后重试"
                                await session.rollback()
                            else:
                                lottery.status = "completed"
                                lottery.drawn_at = dt.datetime.now(dt.UTC)
                if error_msg:
                    await session.rollback()
                else:
                    await session.commit()

        if error_msg:
            await q.answer(error_msg, show_alert=True)
        else:
            if draw_announcement and result_chat_id is not None:
                if result_pin_enabled and result_message_id is not None:
                    try:
                        await context.bot.pin_chat_message(chat_id=result_chat_id, message_id=result_message_id)
                    except Exception:
                        pass
                await q.answer(f"🎉 参与成功！当前人数: {participant_count}，已满员开奖！", show_alert=True)
            else:
                await q.answer(f"🎉 参与成功！当前人数: {participant_count}", show_alert=True)
