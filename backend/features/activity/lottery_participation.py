from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, replace

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


@dataclass(frozen=True)
class _JoinFlow:
    controller: object
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    lottery_id: int
    chat: object
    user: object
    query: object


@dataclass(frozen=True)
class _JoinOutcome:
    error_msg: str | None = None
    participant_count: int = 0
    joined_lottery: object | None = None
    draw_announcement: str | None = None
    result_pin_enabled: bool = False
    result_chat_id: int | None = None
    result_message_id: int | None = None
    subscribe_notice_text: str | None = None
    subscribe_notice_markup: object | None = None


async def _check_join_subscription(flow: _JoinFlow, lottery, rules: dict) -> _JoinOutcome | None:
    if not requires_lottery_subscribe(lottery):
        return None
    targets = get_lottery_subscribe_targets(rules)
    allowed, reason = await check_lottery_subscribe_membership(
        flow.context, targets, flow.user.id,
        check_mode=rules.get("subscribe_check_mode") or "all",
    )
    if allowed:
        return None
    error = reason or "请先关注指定频道/群组后再参与抽奖。"
    return _JoinOutcome(
        error_msg=error, subscribe_notice_text=error,
        subscribe_notice_markup=build_lottery_subscribe_markup(targets),
    )


async def _join_points_and_member(flow: _JoinFlow, rules: dict):
    point_type_id = rules.get("point_type_id")
    if point_type_id:
        points = await PointsExtendedService.get_custom_point_balance(
            flow.session, chat_id=flow.chat.id,
            type_id=int(point_type_id), user_id=flow.user.id,
        )
        point_type_name = rules.get("point_type_name") or "积分"
    else:
        points = await get_balance(flow.session, flow.chat.id, flow.user.id)
        point_type_name = "积分"
    stmt = select(ChatMember).where(
        ChatMember.chat_id == flow.chat.id, ChatMember.user_id == flow.user.id
    )
    member = (await flow.session.execute(stmt)).scalar_one_or_none()
    return point_type_id, point_type_name, points, member.joined_at if member else None


async def _charge_join_cost(flow: _JoinFlow, lottery, point_type_id) -> str | None:
    if lottery.participation_cost <= 0:
        return None
    if point_type_id:
        balance = await PointsExtendedService.get_custom_point_balance(
            flow.session, chat_id=flow.chat.id,
            type_id=int(point_type_id), user_id=flow.user.id,
        )
        if balance < lottery.participation_cost:
            return "积分不足，无法参与"
        await PointsExtendedService.adjust_custom_points(
            flow.session, chat_id=flow.chat.id, type_id=int(point_type_id),
            user_id=flow.user.id, delta=-lottery.participation_cost,
            operator_user_id=None, reason_note=f"参与抽奖: {lottery.title}",
        )
        return None
    success, _ = await change_points(
        flow.session, chat_id=flow.chat.id, user_id=flow.user.id,
        amount=-lottery.participation_cost,
        txn_type=PointsTxnType.lottery_join.value, reason=f"参与抽奖: {lottery.title}",
    )
    return None if success else "积分不足，无法参与"


async def _join_lottery_user(flow: _JoinFlow, lottery) -> _JoinOutcome:
    rules = lottery.qualification_rules or {}
    subscription_error = await _check_join_subscription(flow, lottery, rules)
    if subscription_error:
        return subscription_error
    point_type_id, point_name, points, joined_at = await _join_points_and_member(flow, rules)
    result = await join_lottery(
        flow.session, lottery_id=flow.lottery_id, user_id=flow.user.id,
        points_balance=points, member_joined_at=joined_at,
    )
    if not result.success:
        return _JoinOutcome(
            error_msg=_join_error_message(result.reason, lottery=lottery, point_type_name=point_name)
        )
    cost_error = await _charge_join_cost(flow, lottery, point_type_id)
    if cost_error:
        error = cost_error if not point_type_id else f"{point_name}不足，无法参与"
        return _JoinOutcome(error_msg=error)
    count = await get_lottery_participant_count(flow.session, flow.lottery_id)
    return _JoinOutcome(participant_count=count, joined_lottery=lottery)


def _full_draw_due(lottery, participant_count: int) -> bool:
    rules = lottery.qualification_rules or {}
    return (
        rules.get("draw_trigger") == "full_participants"
        and lottery.max_participants > 0
        and participant_count >= lottery.max_participants
    )


def _preset_draw_ids(rules: dict) -> list[int]:
    raw_ids = rules.get("preset_winner_ids") or rules.get("fixed_winner_ids") or []
    return [int(user_id) for user_id in raw_ids if str(user_id).isdigit()]


async def _full_draw_eligible_ids(flow: _JoinFlow, lottery, rules: dict):
    if not requires_lottery_subscribe(lottery):
        return None
    participants = await get_lottery_participants(flow.session, flow.lottery_id)
    candidate_ids = {int(item.user_id) for item in participants}
    candidate_ids.update(_preset_draw_ids(rules))
    return await filter_lottery_subscribed_user_ids(
        flow.context, get_lottery_subscribe_targets(rules), candidate_ids,
        check_mode=rules.get("subscribe_check_mode") or "all",
    )


async def _send_full_draw_announcement(flow: _JoinFlow, lottery, announcement: str, *, log_event: str):
    try:
        sent = await flow.context.bot.send_message(
            chat_id=lottery.chat_id, text=announcement, parse_mode="HTML"
        )
        return sent.message_id
    except Exception as exc:
        log.error(log_event, lottery_id=flow.lottery_id, error=str(exc))
        return None


async def _build_full_draw_announcement(
    flow: _JoinFlow, lottery, winners, *, eligible_ids, participant_count: int
):
    from backend.features.activity.services.lottery_service import (
        distribute_lottery_rewards,
        generate_lottery_announcement,
    )

    if winners:
        result = await flow.session.execute(
            select(TgUser).where(TgUser.id.in_([item.user_id for item in winners]))
        )
        users = {user.id: user for user in result.scalars().all()}
        await distribute_lottery_rewards(flow.session, lottery, winners)
        return (
            generate_lottery_announcement(lottery, winners, users),
            "full_participant_lottery_announcement_failed",
        )
    if requires_lottery_subscribe(lottery) and eligible_ids is not None:
        return (
            _format_full_draw_no_eligible_announcement(
                lottery, participant_count=participant_count
            ),
            "full_participant_lottery_no_eligible_announcement_failed",
        )
    return None


async def _complete_full_draw(flow: _JoinFlow, outcome: _JoinOutcome) -> _JoinOutcome:
    lottery = outcome.joined_lottery
    if lottery is None or not _full_draw_due(lottery, outcome.participant_count):
        return outcome
    from backend.features.activity.services.lottery_service import (
        get_or_create_lottery_setting,
        perform_random_draw,
    )
    rules = lottery.qualification_rules or {}
    eligible_ids = await _full_draw_eligible_ids(flow, lottery, rules)
    kwargs = {} if eligible_ids is None else {"eligible_user_ids": eligible_ids}
    winners = await perform_random_draw(flow.session, lottery, **kwargs)
    announcement_result = await _build_full_draw_announcement(
        flow, lottery, winners,
        eligible_ids=eligible_ids, participant_count=outcome.participant_count,
    )
    if announcement_result is None:
        return outcome
    announcement, log_event = announcement_result
    setting = await get_or_create_lottery_setting(flow.session, lottery.chat_id)
    message_id = await _send_full_draw_announcement(
        flow, lottery, announcement, log_event=log_event
    )
    if message_id is None:
        return replace(outcome, error_msg="已满员，但开奖结果公告发送失败，请稍后重试")
    lottery.status = "completed"
    lottery.drawn_at = dt.datetime.now(dt.UTC)
    return replace(
        outcome, draw_announcement=announcement,
        result_pin_enabled=setting.result_pin_enabled,
        result_chat_id=lottery.chat_id, result_message_id=message_id,
    )


async def _send_subscribe_notice(flow: _JoinFlow, outcome: _JoinOutcome) -> None:
    if not outcome.subscribe_notice_text or outcome.subscribe_notice_markup is None:
        return
    try:
        notice = await flow.context.bot.send_message(
            chat_id=flow.chat.id, text=outcome.subscribe_notice_text,
            reply_markup=outcome.subscribe_notice_markup,
            reply_to_message_id=getattr(flow.query.message, "message_id", None),
            allow_sending_without_reply=True,
        )
        _schedule_message_delete(
            flow.context, notice, LOTTERY_SUBSCRIBE_NOTICE_DELETE_SECONDS,
            name="activity.lottery_subscribe_notice_delete",
        )
    except Exception as exc:
        log.warning(
            "lottery_force_subscribe_notice_failed",
            lottery_id=flow.lottery_id, error=str(exc),
        )


async def _pin_join_result(flow: _JoinFlow, outcome: _JoinOutcome) -> None:
    if not outcome.result_pin_enabled or outcome.result_message_id is None:
        return
    try:
        await flow.context.bot.pin_chat_message(
            chat_id=outcome.result_chat_id, message_id=outcome.result_message_id
        )
    except Exception as exc:
        log.warning(
            "lottery_result_pin_failed", lottery_id=flow.lottery_id,
            chat_id=outcome.result_chat_id,
            message_id=outcome.result_message_id, error=str(exc),
        )


async def _send_join_success(flow: _JoinFlow, outcome: _JoinOutcome) -> None:
    if outcome.joined_lottery is None:
        return
    full_draw = bool(outcome.draw_announcement and outcome.result_chat_id is not None)
    try:
        await flow.context.bot.send_message(
            chat_id=flow.chat.id,
            text=_format_join_success_message(
                user=flow.user, lottery=outcome.joined_lottery,
                participant_count=outcome.participant_count,
                full_draw_completed=full_draw,
            ),
            parse_mode="HTML",
            reply_to_message_id=getattr(flow.query.message, "message_id", None),
            allow_sending_without_reply=True,
        )
    except Exception as exc:
        log.error(
            "lottery_join_success_message_failed",
            lottery_id=flow.lottery_id, error=str(exc),
        )


async def _respond_join(flow: _JoinFlow, outcome: _JoinOutcome) -> None:
    if outcome.error_msg:
        await flow.query.answer(outcome.error_msg, show_alert=True)
        await _send_subscribe_notice(flow, outcome)
        return
    full_draw = bool(outcome.draw_announcement and outcome.result_chat_id is not None)
    if full_draw:
        await _pin_join_result(flow, outcome)
        text = f"🎉 参与成功！当前人数: {outcome.participant_count}，已满员开奖！"
    else:
        text = f"🎉 参与成功！当前人数: {outcome.participant_count}"
    await flow.query.answer(text, show_alert=True)
    await _send_join_success(flow, outcome)


async def _process_join(flow: _JoinFlow) -> _JoinOutcome:
    lottery = await get_lottery(flow.session, flow.lottery_id)
    if lottery is None:
        return _JoinOutcome(error_msg="抽奖不存在。")
    if lottery.chat_id != flow.chat.id:
        return _JoinOutcome(error_msg="此抽奖不属于当前群组。")
    outcome = await _join_lottery_user(flow, lottery)
    if outcome.error_msg:
        return outcome
    return await _complete_full_draw(flow, outcome)


class LotteryParticipationMixin:
    async def handle_join(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
    ) -> None:
        query = update.callback_query
        chat = update.effective_chat
        user = update.effective_user
        if chat.type == "private":
            await self.message_helper.safe_edit(update, "请在群里使用。")
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            flow = _JoinFlow(
                controller=self, update=update, context=context, session=session,
                lottery_id=lottery_id, chat=chat, user=user, query=query,
            )
            outcome = await _process_join(flow)
            if outcome.error_msg:
                await session.rollback()
            else:
                await session.commit()
        await _respond_join(flow, outcome)
