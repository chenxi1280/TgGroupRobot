"""抽奖自动开奖任务"""

from __future__ import annotations

import datetime as dt
import html
from types import SimpleNamespace

import structlog
from sqlalchemy import func, or_, select

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)

REMINDER_ONE_HOUR = "1h"
REMINDER_FIVE_MINUTES = "5m"
REMINDER_WINDOWS: tuple[tuple[str, dt.timedelta, str], ...] = (
    (REMINDER_FIVE_MINUTES, dt.timedelta(minutes=5), "5 分钟内"),
    (REMINDER_ONE_HOUR, dt.timedelta(hours=1), "1 小时内"),
)


def _format_local_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _time_deadline_reminder_key(lottery, now: dt.datetime) -> tuple[str, str] | None:
    remaining = lottery.draw_time - now
    if remaining <= dt.timedelta(0):
        return None
    for key, window, label in REMINDER_WINDOWS:
        if remaining <= window:
            return key, label
    return None


def _is_time_deadline_lottery(lottery) -> bool:
    rules = lottery.qualification_rules or {}
    return rules.get("draw_trigger") in {None, "time_deadline"}


def _get_sent_reminders(lottery) -> set[str]:
    rules = lottery.qualification_rules or {}
    raw = rules.get("time_reminders_sent") or []
    if isinstance(raw, str):
        return {raw}
    return {str(item) for item in raw}


def _mark_reminder_sent(lottery, key: str) -> None:
    rules = dict(lottery.qualification_rules or {})
    sent = sorted(_get_sent_reminders(lottery) | {key})
    rules["time_reminders_sent"] = sent
    lottery.qualification_rules = rules


def _format_deadline_reminder(lottery, *, participant_count: int, label: str) -> str:
    title = html.escape(lottery.title or "抽奖")
    deadline = html.escape(_format_local_time(lottery.draw_time))
    count_label = str(participant_count)
    if int(lottery.max_participants or 0) > 0:
        count_label = f"{participant_count}/{int(lottery.max_participants)}"
    return "\n".join(
        [
            f"⏰ 抽奖【{title}】将在 {html.escape(label)} 开奖",
            f"截止时间：<code>{deadline}</code>",
            f"当前参与人数：{html.escape(count_label)}",
            "",
            "还没参与的成员请尽快点击原抽奖按钮参与。",
        ]
    )


def _format_no_participants_announcement(lottery, *, participant_count: int | None = None) -> str:
    title = html.escape(lottery.title or "抽奖")
    lines = ["⏰ 抽奖已结束，已停止参与。"]
    if participant_count is not None:
        lines.append(f"👥 本次参与人数：{participant_count}")
    lines.extend(
        [
            "",
            f"🎉 抽奖【{title}】开奖结果",
            "",
            "😔 因无人参与，本次抽奖流拍。",
            "可调整门槛后重新发起。",
        ]
    )
    return "\n".join(lines)


def _format_no_eligible_announcement(lottery, *, participant_count: int) -> str:
    title = html.escape(lottery.title or "抽奖")
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


def _format_draw_result_with_close_notice(announcement: str, *, participant_count: int | None = None) -> str:
    lines = ["⏰ 抽奖已结束，已停止参与。"]
    if participant_count is not None:
        lines.append(f"👥 本次参与人数：{participant_count}")
    return "\n".join(lines) + "\n\n" + announcement


async def _participant_count(session, lottery_id: int) -> int:
    from backend.platform.db.schema.models.core import LotteryParticipant

    result = await session.execute(
        select(func.count(LotteryParticipant.id)).where(LotteryParticipant.lottery_id == lottery_id)
    )
    return int(result.scalar() or 0)


async def _send_lottery_message(app, lottery, text: str, *, reply_to_source: bool = True):
    kwargs = {
        "chat_id": lottery.chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_to_source and lottery.message_id:
        kwargs["reply_to_message_id"] = lottery.message_id
        kwargs["allow_sending_without_reply"] = True
    return await PublishService.send(SimpleNamespace(bot=app.bot, application=app), **kwargs)


async def _send_lottery_plain_message(app, lottery, text: str):
    return await PublishService.send(
        SimpleNamespace(bot=app.bot, application=app),
        chat_id=lottery.chat_id,
        text=text,
        parse_mode="HTML",
    )


async def _send_lottery_result_message(app, lottery, text: str):
    try:
        return await _send_lottery_message(app, lottery, text)
    except Exception as first_exc:
        log.warning("auto_draw_result_publish_service_failed", lottery_id=lottery.id, error=str(first_exc))
        try:
            return await _send_lottery_plain_message(app, lottery, text)
        except Exception as second_exc:
            log.error(
                "auto_draw_result_publish_service_fallback_failed",
                lottery_id=lottery.id,
                first_error=str(first_exc),
                error=str(second_exc),
            )
            raise second_exc from first_exc


async def _lock_pending_lottery(session, lottery_model, lottery_id: int):
    result = await session.execute(
        select(lottery_model)
        .where(
            lottery_model.id == lottery_id,
            lottery_model.status == "pending",
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


def _parse_positive_user_ids(values) -> list[int]:
    user_ids: list[int] = []
    for raw_user_id in values or []:
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        if user_id > 0:
            user_ids.append(user_id)
    return user_ids


async def _get_subscribed_eligible_user_ids(app, session, lottery) -> tuple[set[int] | None, bool]:
    from backend.features.activity.services.lottery_service_queries import get_lottery_participants
    from backend.features.activity.services.lottery_subscription import (
        filter_lottery_subscribed_user_ids,
        get_lottery_subscribe_targets,
        requires_lottery_subscribe,
    )

    if not requires_lottery_subscribe(lottery):
        return None, False
    rules = lottery.qualification_rules or {}
    participants = await get_lottery_participants(session, lottery.id)
    preset_values = rules.get("preset_winner_ids") or rules.get("fixed_winner_ids") or []
    preset_ids = _parse_positive_user_ids(preset_values)
    candidate_ids = {int(participant.user_id) for participant in participants} | set(preset_ids)
    eligible_ids = await filter_lottery_subscribed_user_ids(
        SimpleNamespace(bot=app.bot),
        get_lottery_subscribe_targets(rules),
        candidate_ids,
        check_mode=rules.get("subscribe_check_mode") or "all",
    )
    return eligible_ids, True


async def _get_due_locked_lottery(session, lottery_model, lottery, *, now: dt.datetime):
    locked = await _lock_pending_lottery(session, lottery_model, lottery.id)
    if locked is None or not _is_time_deadline_lottery(locked):
        return None
    return locked if locked.draw_time <= now else None


async def _perform_eligible_draw(
    session,
    lottery,
    eligible_user_ids,
    *,
    perform_random_draw,
):
    if eligible_user_ids is None:
        return await perform_random_draw(session, lottery)
    return await perform_random_draw(
        session, lottery, eligible_user_ids=eligible_user_ids
    )


async def _build_draw_announcement(
    session,
    lottery,
    winners,
    *,
    participant_total: int,
    eligible_filter_applied: bool,
    generate_lottery_announcement,
    distribute_lottery_rewards,
    user_model,
) -> str:
    if not winners:
        if eligible_filter_applied:
            return _format_no_eligible_announcement(
                lottery, participant_count=participant_total
            )
        return _format_no_participants_announcement(
            lottery, participant_count=participant_total
        )
    user_ids = [winner.user_id for winner in winners]
    user_result = await session.execute(select(user_model).where(user_model.id.in_(user_ids)))
    users = {user.id: user for user in user_result.scalars().all()}
    await distribute_lottery_rewards(session, lottery, winners)
    return _format_draw_result_with_close_notice(
        generate_lottery_announcement(lottery, winners, users),
        participant_count=participant_total,
    )


async def _publish_and_complete_draw(
    app,
    session,
    lottery,
    *,
    announcement: str,
    now: dt.datetime,
    winners,
) -> None:
    try:
        await _send_lottery_result_message(app, lottery, announcement)
    except Exception as exc:
        log.error("auto_draw_announcement_failed", lottery_id=lottery.id, error=str(exc))
        await session.rollback()
        return
    lottery.status = "completed"
    lottery.drawn_at = now
    await session.commit()
    log.info(
        "auto_draw_lottery_success",
        lottery_id=lottery.id,
        chat_id=lottery.chat_id,
        winners_count=len(winners),
    )


class LotteryTask(ScheduledTask):
    """抽奖自动开奖任务"""

    def __init__(self):
        config = TASK_CONFIG["lottery"]
        super().__init__(
            name="lottery",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行开奖逻辑"""
        from backend.features.activity.services.lottery_service import (
            distribute_lottery_rewards,
            generate_lottery_announcement,
            perform_random_draw,
        )
        from backend.platform.db.schema.models.core import Lottery, TgUser

        db = app.bot_data["db"]

        async with db.session_factory() as session:
            now = dt.datetime.now(dt.UTC)
            reminder_horizon = now + dt.timedelta(hours=1)
            stmt = select(Lottery).where(
                Lottery.status == "pending",
                Lottery.draw_time <= reminder_horizon,
                or_(
                    Lottery.qualification_rules["draw_trigger"].astext.is_(None),
                    Lottery.qualification_rules["draw_trigger"].astext == "time_deadline",
                ),
            )
            result = await session.execute(stmt)
            lotteries = result.scalars().all()

            for lottery in lotteries:
                await self._process_candidate_lottery(
                    app,
                    session,
                    lottery,
                    now=now,
                    perform_random_draw=perform_random_draw,
                    generate_lottery_announcement=generate_lottery_announcement,
                    distribute_lottery_rewards=distribute_lottery_rewards,
                    lottery_model=Lottery,
                    user_model=TgUser,
                )

    async def _process_candidate_lottery(
        self,
        app,
        session,
        lottery,
        *,
        now,
        perform_random_draw,
        generate_lottery_announcement,
        distribute_lottery_rewards,
        lottery_model,
        user_model,
    ) -> None:
        try:
            if lottery.draw_time > now:
                await self._send_due_reminder(app, session, lottery, now=now)
                return
            await self._draw_due_lottery(
                app,
                session,
                lottery,
                now=now,
                perform_random_draw=perform_random_draw,
                generate_lottery_announcement=generate_lottery_announcement,
                distribute_lottery_rewards=distribute_lottery_rewards,
                lottery_model=lottery_model,
                user_model=user_model,
            )
        except Exception as exc:
            log.error("auto_draw_lottery_failed", lottery_id=lottery.id, error=str(exc))
            await session.rollback()

    async def _send_due_reminder(self, app, session, lottery, *, now: dt.datetime) -> None:
        locked_lottery = await _lock_pending_lottery(session, lottery.__class__, lottery.id)
        if locked_lottery is None or not _is_time_deadline_lottery(locked_lottery):
            return
        lottery = locked_lottery
        if lottery.draw_time <= now:
            return
        reminder = _time_deadline_reminder_key(lottery, now)
        if reminder is None:
            return
        key, label = reminder
        if key in _get_sent_reminders(lottery):
            return

        participant_total = await _participant_count(session, lottery.id)
        text = _format_deadline_reminder(lottery, participant_count=participant_total, label=label)
        try:
            await _send_lottery_message(app, lottery, text)
        except Exception as exc:
            log.error("lottery_deadline_reminder_failed", lottery_id=lottery.id, reminder=key, error=str(exc))
            await session.rollback()
            return

        _mark_reminder_sent(lottery, key)
        await session.commit()
        log.info("lottery_deadline_reminder_sent", lottery_id=lottery.id, reminder=key)

    async def _draw_due_lottery(
        self,
        app,
        session,
        lottery,
        *,
        now: dt.datetime,
        perform_random_draw,
        generate_lottery_announcement,
        distribute_lottery_rewards,
        lottery_model,
        user_model,
    ) -> None:
        locked_lottery = await _get_due_locked_lottery(
            session, lottery_model, lottery, now=now
        )
        if locked_lottery is None:
            return
        lottery = locked_lottery
        participant_total = await _participant_count(session, lottery.id)
        eligible_user_ids, filter_applied = await _get_subscribed_eligible_user_ids(
            app, session, lottery
        )
        winners = await _perform_eligible_draw(
            session,
            lottery,
            eligible_user_ids,
            perform_random_draw=perform_random_draw,
        )
        announcement = await _build_draw_announcement(
            session,
            lottery,
            winners,
            participant_total=participant_total,
            eligible_filter_applied=filter_applied,
            generate_lottery_announcement=generate_lottery_announcement,
            distribute_lottery_rewards=distribute_lottery_rewards,
            user_model=user_model,
        )

        await _publish_and_complete_draw(
            app,
            session,
            lottery,
            announcement=announcement,
            now=now,
            winners=winners,
        )
