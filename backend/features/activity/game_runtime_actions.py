from __future__ import annotations

import datetime as dt

import structlog
from dataclasses import dataclass
from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.game_panels import (
    blackjack_round_keyboard,
    k3_fee_confirmation,
    show_blackjack_panel,
    show_k3_panel,
)
from backend.features.activity.game_notice_delivery import deliver_game_notices
from backend.features.activity.game_web_notifications import queue_group_blackjack, queue_web_game
from backend.features.activity.room_games.fees import MAX_ROOM_FEE, fee_settings
from backend.features.activity.services.game_k3 import K3_OPTION_LABELS, K3_ROUND_SECONDS
from backend.features.activity.services.game_service import (
    blackjack_hit,
    blackjack_stand,
    create_or_join_k3_round,
    place_blackjack_bet,
    format_blackjack_round_text,
    get_active_blackjack_round,
    get_or_create_setting,
    k3_guess_label,
    MAX_GAME_BET_POINTS,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _RuntimeFlow:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    db: Database
    user: object
    chat_id: int
    data: CallbackParser
    game: str | None
    action: str | None


async def _runtime_bet(flow: _RuntimeFlow, index: int) -> int | None:
    try:
        bet = int(flow.data.get(index, "0") or "0")
    except ValueError:
        await answer_callback_query_safely(flow.update, "下注参数无效", show_alert=True)
        return None
    if bet <= 0 or bet > MAX_GAME_BET_POINTS:
        await answer_callback_query_safely(
            flow.update, f"下注积分必须在 1 到 {MAX_GAME_BET_POINTS} 之间", show_alert=True
        )
        return None
    return bet


async def _ensure_runtime_user(session, user) -> None:
    await ensure_user(
        session, user.id, user.username, first_name=user.first_name,
        last_name=user.last_name, language_code=user.language_code,
    )


async def _refresh_runtime_panel(flow: _RuntimeFlow) -> None:
    if flow.game == "k3":
        await show_k3_panel(flow.context, flow.db, flow.chat_id)
        await answer_callback_query_safely(flow.update, "已刷新快三面板", show_alert=False)
        return
    await show_blackjack_panel(flow.context, flow.db, flow.chat_id)
    async with flow.db.session_factory() as session:
        round_obj, participant = await get_active_blackjack_round(
            session, flow.chat_id, flow.user.id
        )
        await session.commit()
    if round_obj and participant and round_obj.announcement_message_id:
        try:
            await flow.context.bot.edit_message_text(
                chat_id=flow.chat_id, message_id=round_obj.announcement_message_id,
                text=format_blackjack_round_text(participant),
                reply_markup=blackjack_round_keyboard(flow.chat_id),
            )
        except Exception as exc:
            log.warning(
                "blackjack_refresh_edit_failed", chat_id=flow.chat_id,
                message_id=round_obj.announcement_message_id,
                user_id=flow.user.id, error=str(exc),
            )
    await answer_callback_query_safely(flow.update, "已刷新黑杰克面板", show_alert=False)


async def _place_runtime_k3_bet(flow: _RuntimeFlow, guess: str, bet: int, *, fee=None, confirmation_id=None):
    async with flow.db.session_factory() as session:
        await _ensure_runtime_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat_id)
        if not setting.k3_enabled:
            await session.commit()
            await answer_callback_query_safely(flow.update, "快三当前未开启", show_alert=True)
            return None
        try:
            current_fee = (await fee_settings(session)).k3
            if fee is None and current_fee:
                text, keyboard = k3_fee_confirmation(flow.chat_id, flow.user.id, guess=guess, bet=bet, fee=current_fee)
                await session.rollback()
                await answer_callback_query_safely(flow.update, "请确认本次下注和台费", show_alert=False)
                await flow.context.bot.send_message(chat_id=flow.chat_id, text=text, reply_markup=keyboard)
                return None
            round_obj, participant = await create_or_join_k3_round(
                session, flow.chat_id, flow.user.id, guess=guess, bet_points=bet,
                expected_fee=fee, confirmation_id=confirmation_id,
            )
        except ValidationError as exc:
            await session.rollback()
            await answer_callback_query_safely(flow.update, str(exc), show_alert=True)
            return None
        count = await session.execute(select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id))
        participant_count = int(count.scalar() or 0)
        notices = []
        if fee:
            web = getattr(flow.context.application.bot_data.get("settings"), "mini_app_enabled", False)
            notices = queue_web_game(session, flow.context.bot, round_obj, participant=participant,
                                     opened=round_obj.creator_user_id == flow.user.id, outcome=None, links_enabled=web)
            await session.flush()
        notice_ids = [notice.id for notice in notices]
        await session.commit()
    if notice_ids:
        await deliver_game_notices(flow.db, flow.context.bot, notice_ids)
    return participant_count


def _confirmed_k3_bet(flow: _RuntimeFlow):
    message = flow.update.callback_query.message
    choice, fee, user_id = (flow.data.get_int_optional(i) for i in (4, 6, 7))
    if user_id != flow.user.id or choice is None or not 0 <= choice < len(K3_OPTION_LABELS):
        return None
    if fee is None or not 1 <= fee <= MAX_ROOM_FEE or not message:
        return None
    if not 0 <= (dt.datetime.now(dt.UTC) - message.date).total_seconds() <= K3_ROUND_SECONDS:
        return None
    return tuple(K3_OPTION_LABELS)[choice], fee, message.message_id


async def _handle_runtime_k3_bet(flow: _RuntimeFlow) -> None:
    bet = await _runtime_bet(flow, 5)
    if bet is None:
        return
    guess, fee, confirmation_id = flow.data.get(4), None, None
    if flow.action == "pay":
        confirmed = _confirmed_k3_bet(flow)
        if confirmed is None:
            await answer_callback_query_safely(flow.update, "该确认已过期或不属于你，请重新发起下注", show_alert=True)
            return
        guess, fee, confirmation_id = confirmed
    count = await _place_runtime_k3_bet(flow, guess, bet, fee=fee, confirmation_id=confirmation_id)
    if count is None:
        return
    await answer_callback_query_safely(
        flow.update, f"下注成功：{k3_guess_label(guess)} {bet}，本局 {count} 人",
        show_alert=False,
    )
    await show_k3_panel(flow.context, flow.db, flow.chat_id)


async def _create_runtime_blackjack(flow: _RuntimeFlow, bet: int):
    async with flow.db.session_factory() as session:
        await _ensure_runtime_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat_id)
        await session.refresh(setting, with_for_update=True)
        if not setting.blackjack_enabled:
            await session.commit()
            await answer_callback_query_safely(flow.update, "黑杰克当前未开启", show_alert=True)
            return None
        try:
            round_obj, participant, outcome = await place_blackjack_bet(session, setting, flow.user.id, bet=bet)
        except ValidationError as exc:
            await session.rollback()
            await answer_callback_query_safely(flow.update, str(exc), show_alert=True)
            return None
        notice = queue_group_blackjack(
            session, round_obj, participant, outcome=outcome, opening=True,
            keyboard=None if outcome else blackjack_round_keyboard(flow.chat_id),
        )
        await session.flush()
        notice_id = notice.id
        await session.commit()
    return notice_id


async def _handle_runtime_blackjack_start(flow: _RuntimeFlow) -> None:
    bet = await _runtime_bet(flow, 4)
    if bet is None:
        return
    notice_id = await _create_runtime_blackjack(flow, bet)
    if notice_id is None:
        return
    await deliver_game_notices(flow.db, flow.context.bot, [notice_id])
    await show_blackjack_panel(flow.context, flow.db, flow.chat_id)
    await answer_callback_query_safely(flow.update, f"黑杰克开局成功：{bet}", show_alert=False)


async def _edit_runtime_blackjack(
    flow: _RuntimeFlow, round_obj, participant, *, outcome
) -> None:
    if not round_obj.announcement_message_id:
        return
    try:
        await flow.context.bot.edit_message_text(
            chat_id=flow.chat_id, message_id=round_obj.announcement_message_id,
            text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
            reply_markup=None if outcome else blackjack_round_keyboard(flow.chat_id),
        )
    except Exception as exc:
        log.warning(
            "blackjack_round_runtime_edit_failed", chat_id=flow.chat_id,
            message_id=round_obj.announcement_message_id,
            user_id=flow.user.id, error=str(exc),
        )


async def _handle_runtime_blackjack_action(flow: _RuntimeFlow) -> None:
    async with flow.db.session_factory() as session:
        round_obj, participant = await get_active_blackjack_round(
            session, flow.chat_id, flow.user.id, lock=True
        )
        if round_obj is None or participant is None:
            await session.commit()
            await answer_callback_query_safely(flow.update, "你当前没有进行中的黑杰克", show_alert=True)
            return
        message = flow.update.callback_query.message
        if message is None or message.message_id != round_obj.announcement_message_id:
            await session.commit()
            await answer_callback_query_safely(flow.update, "这是旧牌局按钮，请使用当前牌局的按钮", show_alert=True)
            return
        if flow.action == "hit":
            _, participant, outcome = await blackjack_hit(session, round_obj, participant)
        else:
            outcome = await blackjack_stand(session, round_obj, participant)
        notice_id = None
        if outcome:
            notice = queue_group_blackjack(session, round_obj, participant, outcome=outcome)
            await session.flush()
            notice_id = notice.id
        await session.commit()
    if notice_id is not None:
        await deliver_game_notices(flow.db, flow.context.bot, [notice_id])
    else:
        await _edit_runtime_blackjack(flow, round_obj, participant, outcome=outcome)
    await show_blackjack_panel(flow.context, flow.db, flow.chat_id)
    await answer_callback_query_safely(flow.update, "已更新当前对局", show_alert=False)


async def _runtime_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return None
    data = CallbackParser.parse(update.callback_query.data or "")
    chat_id = data.get_int_optional(3)
    if chat_id is None or chat_id != update.effective_chat.id:
        await answer_callback_query_safely(update, "参数错误", show_alert=True)
        return None
    db: Database = context.application.bot_data["db"]
    return _RuntimeFlow(
        update=update, context=context, db=db, user=update.effective_user,
        chat_id=chat_id, data=data, game=data.get(1), action=data.get(2),
    )


async def handle_game_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = await _runtime_flow(update, context)
    if flow is None:
        return
    if flow.action == "refresh" and flow.game in {"k3", "bj"}:
        await _refresh_runtime_panel(flow)
        return
    if flow.game == "k3" and flow.action in {"bet", "pay"}:
        await _handle_runtime_k3_bet(flow)
        return
    if flow.game == "bj" and flow.action == "start":
        await _handle_runtime_blackjack_start(flow)
        return
    if flow.game == "bj" and flow.action in {"hit", "stand"}:
        await _handle_runtime_blackjack_action(flow)
        return
    await answer_callback_query_safely(flow.update, "暂不支持该操作", show_alert=True)
