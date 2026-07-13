from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.enums import LotteryDrawMode
from backend.features.activity.services.lottery_service import (
    get_lottery,
    get_lottery_participants,
    get_or_create_lottery_setting,
)
from backend.features.activity.services.lottery_subscription import (
    filter_lottery_subscribed_user_ids,
    get_lottery_subscribe_targets,
    requires_lottery_subscribe,
)
from backend.features.activity.ui.lottery import manual_draw_summary_keyboard

log = structlog.get_logger(__name__)


def _valid_user_ids(raw_user_ids) -> list[int]:
    user_ids = []
    for raw_user_id in raw_user_ids:
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        if user_id > 0:
            user_ids.append(user_id)
    return user_ids


@dataclass(frozen=True)
class _DrawFlow:
    controller: object
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    lottery: object
    target_chat_id: int | None


def _draw_rules_and_presets(lottery) -> tuple[dict, list[int]]:
    rules = lottery.qualification_rules or {}
    raw_ids = rules.get("preset_winner_ids") or rules.get("fixed_winner_ids") or []
    return rules, _valid_user_ids(raw_ids)


def _eligible_participants(participants, eligible_ids: set[int]):
    return [
        participant
        for participant in participants
        if int(participant.user_id) in eligible_ids
    ]


async def _filter_draw_candidates(flow: _DrawFlow, participants):
    rules, preset_ids = _draw_rules_and_presets(flow.lottery)
    if not requires_lottery_subscribe(flow.lottery):
        return participants, preset_ids, None
    candidate_ids = {int(participant.user_id) for participant in participants}
    candidate_ids.update(preset_ids)
    eligible_ids = await filter_lottery_subscribed_user_ids(
        flow.context,
        get_lottery_subscribe_targets(rules),
        candidate_ids,
        check_mode=rules.get("subscribe_check_mode") or "all",
    )
    filtered_participants = _eligible_participants(participants, eligible_ids)
    return (
        filtered_participants,
        [item for item in preset_ids if item in eligible_ids],
        eligible_ids,
    )


async def _show_manual_draw(flow: _DrawFlow, participants) -> None:
    await flow.session.commit()
    user_ids = [participant.user_id for participant in participants]
    result = await flow.session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))
    users = {user.id: user for user in result.scalars().all()}
    for participant in participants:
        participant.user_info = users.get(participant.user_id)
    prize_count = sum(int(prize.get("quantity", 1)) for prize in flow.lottery.prizes)
    text = (
        "📋 手动选择中奖人\n\n"
        f"抽奖: {flow.lottery.title}\n参与人数: {len(participants)}\n"
        f"奖品数量: {prize_count}\n\n请为每个奖项选择中奖人："
    )
    keyboard = manual_draw_summary_keyboard(
        flow.lottery.chat_id, flow.lottery.id, flow.lottery.prizes
    )
    await flow.controller.message_helper.safe_edit(
        flow.update, text=text, reply_markup=keyboard
    )


def _is_private_draw(flow: _DrawFlow) -> bool:
    chat = flow.update.effective_chat
    return (
        flow.target_chat_id is not None and chat is not None and chat.type == "private"
    )


async def _publish_private_draw(
    flow: _DrawFlow, announcement: str, *, pin_enabled: bool
) -> None:
    try:
        sent = await flow.context.bot.send_message(
            chat_id=flow.lottery.chat_id, text=announcement, parse_mode="HTML"
        )
    except Exception as exc:
        log.error(
            "lottery_manual_draw_send_failed",
            lottery_id=flow.lottery.id,
            chat_id=flow.lottery.chat_id,
            error=str(exc),
        )
        await flow.session.rollback()
        await flow.controller.message_helper.safe_edit(
            flow.update, text="❌ 开奖结果发送失败，可能机器人已被移出群组。"
        )
        return
    if pin_enabled:
        try:
            await flow.context.bot.pin_chat_message(
                chat_id=flow.lottery.chat_id, message_id=sent.message_id
            )
        except Exception as exc:
            log.warning(
                "lottery_manual_draw_pin_failed",
                lottery_id=flow.lottery.id,
                chat_id=flow.lottery.chat_id,
                message_id=sent.message_id,
                error=str(exc),
            )
    await flow.session.commit()
    await flow.controller.message_helper.safe_edit(
        flow.update, text="✅ 已在群内完成开奖并发布结果。"
    )


async def _publish_draw(
    flow: _DrawFlow, announcement: str, *, pin_enabled: bool
) -> None:
    if _is_private_draw(flow):
        await _publish_private_draw(flow, announcement, pin_enabled=pin_enabled)
        return
    sent = await flow.controller.message_helper.safe_edit(
        flow.update, text=announcement, parse_mode="HTML"
    )
    if not sent:
        await flow.session.rollback()
        return
    await flow.session.commit()


async def _perform_draw(flow: _DrawFlow, eligible_user_ids) -> None:
    from backend.features.activity.services.lottery_service import (
        distribute_lottery_rewards,
        generate_lottery_announcement,
        perform_random_draw,
    )

    kwargs = (
        {} if eligible_user_ids is None else {"eligible_user_ids": eligible_user_ids}
    )
    winners = await perform_random_draw(flow.session, flow.lottery, **kwargs)
    if not winners:
        await flow.controller.message_helper.safe_edit(flow.update, "没有人参与抽奖。")
        await flow.session.commit()
        return
    user_ids = [winner.user_id for winner in winners]
    result = await flow.session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))
    users = {user.id: user for user in result.scalars().all()}
    await distribute_lottery_rewards(flow.session, flow.lottery, winners)
    setting = await get_or_create_lottery_setting(flow.session, flow.lottery.chat_id)
    flow.lottery.status = "completed"
    flow.lottery.drawn_at = dt.datetime.now(dt.timezone.utc)
    announcement = generate_lottery_announcement(flow.lottery, winners, users)
    await _publish_draw(flow, announcement, pin_enabled=setting.result_pin_enabled)


class LotteryDrawMixin:
    async def handle_draw(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
        *,
        target_chat_id: int | None = None,
    ) -> None:
        chat = update.effective_chat
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                await self.message_helper.safe_edit(update, "抽奖不存在。")
                await session.commit()
                return
            current_chat_id = target_chat_id if target_chat_id is not None else chat.id
            if lottery.chat_id != current_chat_id:
                await self.message_helper.safe_edit(update, "此抽奖不属于当前群组。")
                await session.commit()
                return
            if lottery.status != "pending":
                await self.message_helper.safe_edit(update, "抽奖已开奖或已取消。")
                await session.commit()
                return
            participants = await get_lottery_participants(session, lottery_id)
            flow = _DrawFlow(
                controller=self,
                update=update,
                context=context,
                session=session,
                lottery=lottery,
                target_chat_id=target_chat_id,
            )
            participants, preset_ids, eligible_ids = await _filter_draw_candidates(
                flow, participants
            )
            if not participants and not preset_ids:
                await self.message_helper.safe_edit(update, "没有人参与抽奖。")
                await session.commit()
                return
            if lottery.draw_mode == LotteryDrawMode.manual.value:
                await _show_manual_draw(flow, participants)
                return
            await _perform_draw(flow, eligible_ids)
