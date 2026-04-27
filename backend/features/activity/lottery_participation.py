from __future__ import annotations

import datetime as dt
import html

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember, TgUser
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.features.activity.services.lottery_service import (
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    join_lottery,
)
from backend.features.activity.services.lottery_subscription import (
    build_lottery_subscribe_markup,
    check_lottery_subscribe_membership,
    filter_lottery_subscribed_user_ids,
    get_lottery_subscribe_targets,
    requires_lottery_subscribe,
)
from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.features.points.services.points_service import change_points, get_balance
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)
LOTTERY_SUBSCRIBE_NOTICE_DELETE_SECONDS = 30


def _user_mention(user) -> str:
    label = format_user_display_name(user, user.id)
    return f'<a href="tg://user?id={user.id}">{html.escape(label)}</a>'


def _format_join_success_message(*, user, lottery, participant_count: int, full_draw_completed: bool) -> str:
    title = html.escape(getattr(lottery, "title", "") or "抽奖")
    max_participants = int(getattr(lottery, "max_participants", 0) or 0)
    count_label = f"{participant_count}/{max_participants}" if max_participants > 0 else str(participant_count)
    lines = [
        f"✅ {_user_mention(user)} 已参与抽奖",
        f"🎁 抽奖：{title}",
        f"👥 当前参与人数：{count_label}",
    ]
    if full_draw_completed:
        lines.append("🎉 已满员，系统已自动开奖。")
    else:
        lines.append("⏳ 请留意原抽奖公告，开奖前会按规则提醒或自动开奖。")
    return "\n".join(lines)


def _join_error_message(reason: str, *, lottery, point_type_name: str) -> str:
    required_points = (lottery.min_points or 0) + (lottery.participation_cost or 0)
    error_messages = {
        "already_joined": "你已经参与过此抽奖了，请等待开奖结果。",
        "lottery_not_open": "抽奖尚未开始，请关注群内抽奖公告。",
        "lottery_closed": "抽奖已结束，不能再参与。",
        "lottery_completed": "抽奖已开奖，请查看群内开奖结果。",
        "insufficient_points": f"{point_type_name}不足，需要至少 {required_points} {point_type_name}。请先获取积分后再参与。",
        "insufficient_invites": "邀请人数未达标，暂时不能参与。请继续邀请新成员后再点击参与。",
        "insufficient_activity": "最近活跃消息数未达标，暂时不能参与。请在群内继续发言互动后再试。",
        "ranking_auto_selection": "本玩法无需手动参与；系统会在开奖时按邀请/活跃排行自动入围，再随机开奖。",
        "max_participants_reached": "参与人数已满，请等待系统自动开奖或管理员开奖。",
        "not_member_long_enough": f"入群天数不足，需要 {lottery.requirement_days} 天以上。满足天数后可再次参与。",
        "outside_join_time": "不在参与时间内，请查看原抽奖公告的截止时间。",
    }
    return error_messages.get(reason, "无法参与抽奖，请联系管理员检查活动配置。")


def _format_full_draw_no_eligible_announcement(lottery, *, participant_count: int) -> str:
    title = html.escape(getattr(lottery, "title", None) or "抽奖")
    return "\n".join(
        [
            "⏰ 抽奖已结束，已停止参与。",
            f"👥 本次参与人数：{participant_count}",
            "",
            f"🎉 抽奖【{title}】开奖结果",
            "",
            "😔 本次无人满足参与条件，未产生中奖人员。",
        ]
    )


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
        joined_lottery = None
        force_subscribe_notice_markup = None
        force_subscribe_notice_text = None

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
                if requires_lottery_subscribe(lottery):
                    subscribe_targets = get_lottery_subscribe_targets(rules)
                    allowed, reason = await check_lottery_subscribe_membership(
                        context,
                        subscribe_targets,
                        user.id,
                        check_mode=rules.get("subscribe_check_mode") or "all",
                    )
                    if not allowed:
                        error_msg = reason or "请先关注指定频道/群组后再参与抽奖。"
                        force_subscribe_notice_text = error_msg
                        force_subscribe_notice_markup = build_lottery_subscribe_markup(subscribe_targets)

                if not error_msg:
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
                        error_msg = _join_error_message(result.reason, lottery=lottery, point_type_name=point_type_name)
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
                    joined_lottery = lottery
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

                        eligible_user_ids = None
                        if requires_lottery_subscribe(lottery):
                            participants = await get_lottery_participants(session, lottery_id)
                            preset_ids = [
                                int(user_id)
                                for user_id in (rules.get("preset_winner_ids") or rules.get("fixed_winner_ids") or [])
                                if str(user_id).isdigit()
                            ]
                            candidate_ids = {int(participant.user_id) for participant in participants} | set(preset_ids)
                            subscribe_targets = get_lottery_subscribe_targets(rules)
                            eligible_user_ids = await filter_lottery_subscribed_user_ids(
                                context,
                                subscribe_targets,
                                candidate_ids,
                                check_mode=rules.get("subscribe_check_mode") or "all",
                            )
                        if eligible_user_ids is None:
                            winners = await perform_random_draw(session, lottery)
                        else:
                            winners = await perform_random_draw(session, lottery, eligible_user_ids=eligible_user_ids)
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
                        elif requires_lottery_subscribe(lottery) and eligible_user_ids is not None:
                            setting = await get_or_create_lottery_setting(session, lottery.chat_id)
                            draw_announcement = _format_full_draw_no_eligible_announcement(
                                lottery,
                                participant_count=participant_count,
                            )
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
                                log.error("full_participant_lottery_no_eligible_announcement_failed", lottery_id=lottery_id, error=str(exc))
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
            if force_subscribe_notice_text and force_subscribe_notice_markup is not None:
                try:
                    sent_notice = await context.bot.send_message(
                        chat_id=chat.id,
                        text=force_subscribe_notice_text,
                        reply_markup=force_subscribe_notice_markup,
                        reply_to_message_id=getattr(q.message, "message_id", None),
                        allow_sending_without_reply=True,
                    )
                    _schedule_message_delete(
                        context,
                        sent_notice,
                        LOTTERY_SUBSCRIBE_NOTICE_DELETE_SECONDS,
                        name="activity.lottery_subscribe_notice_delete",
                    )
                except Exception as exc:
                    log.warning("lottery_force_subscribe_notice_failed", lottery_id=lottery_id, error=str(exc))
        else:
            full_draw_completed = bool(draw_announcement and result_chat_id is not None)
            if draw_announcement and result_chat_id is not None:
                if result_pin_enabled and result_message_id is not None:
                    try:
                        await context.bot.pin_chat_message(chat_id=result_chat_id, message_id=result_message_id)
                    except Exception:
                        pass
                await q.answer(f"🎉 参与成功！当前人数: {participant_count}，已满员开奖！", show_alert=True)
            else:
                await q.answer(f"🎉 参与成功！当前人数: {participant_count}", show_alert=True)
            if joined_lottery is not None:
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=_format_join_success_message(
                            user=user,
                            lottery=joined_lottery,
                            participant_count=participant_count,
                            full_draw_completed=full_draw_completed,
                        ),
                        parse_mode="HTML",
                        reply_to_message_id=getattr(q.message, "message_id", None),
                        allow_sending_without_reply=True,
                    )
                except Exception as exc:
                    log.error("lottery_join_success_message_failed", lottery_id=lottery_id, error=str(exc))
