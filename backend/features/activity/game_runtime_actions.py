from __future__ import annotations

import structlog
from dataclasses import dataclass
from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.game_panels import (
    blackjack_round_keyboard,
    show_blackjack_panel,
    show_k3_panel,
)
from backend.features.activity.services.game_service import (
    blackjack_hit,
    blackjack_stand,
    create_or_join_k3_round,
    finalize_blackjack_round,
    format_blackjack_round_text,
    get_active_k3_round,
    get_active_blackjack_round,
    get_or_create_setting,
    get_round_points_chat_id,
    k3_guess_label,
    MAX_GAME_BET_POINTS,
    resolve_points_chat_id,
    start_blackjack_round,
)
from backend.features.points.services.points_service import change_points
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user
_HANDLE_GAME_RUNTIME_CALLBACK_THRESHOLD_2 = 2
_HANDLE_GAME_RUNTIME_CALLBACK_THRESHOLD_21 = 21


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


async def _place_runtime_k3_bet(flow: _RuntimeFlow, guess: str, bet: int):
    async with flow.db.session_factory() as session:
        await _ensure_runtime_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat_id)
        if not setting.k3_enabled:
            await session.commit()
            await answer_callback_query_safely(flow.update, "快三当前未开启", show_alert=True)
            return None
        active_round = await get_active_k3_round(session, flow.chat_id)
        default_chat_id = resolve_points_chat_id(setting, flow.chat_id)
        points_chat_id = get_round_points_chat_id(active_round, default_chat_id) if active_round else default_chat_id
        ok, balance = await change_points(
            session, points_chat_id, flow.user.id, amount=-bet,
            txn_type=PointsTxnType.penalty.value, reason="快三下注",
        )
        if not ok:
            await session.commit()
            await answer_callback_query_safely(flow.update, f"积分不足，当前余额 {balance}", show_alert=True)
            return None
        try:
            round_obj, _ = await create_or_join_k3_round(
                session, flow.chat_id, flow.user.id, guess=guess,
                bet_points=bet, points_chat_id=points_chat_id,
            )
        except ValidationError as exc:
            await session.rollback()
            await answer_callback_query_safely(flow.update, str(exc), show_alert=True)
            return None
        count = await session.execute(select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id))
        participant_count = int(count.scalar() or 0)
        await session.commit()
    return participant_count


async def _handle_runtime_k3_bet(flow: _RuntimeFlow) -> None:
    bet = await _runtime_bet(flow, 5)
    if bet is None:
        return
    guess = flow.data.get(4) or ""
    count = await _place_runtime_k3_bet(flow, guess, bet)
    if count is None:
        return
    await show_k3_panel(flow.context, flow.db, flow.chat_id)
    await answer_callback_query_safely(
        flow.update, f"下注成功：{k3_guess_label(guess)} {bet}，本局 {count} 人",
        show_alert=False,
    )


async def _runtime_blackjack_outcome(session, round_obj, participant):
    cards = (participant.choice_data or {}).get("player_cards") or []
    if len(cards) != _HANDLE_GAME_RUNTIME_CALLBACK_THRESHOLD_2:
        return None
    from backend.features.activity.services.game_service import blackjack_total
    if blackjack_total(cards) != _HANDLE_GAME_RUNTIME_CALLBACK_THRESHOLD_21:
        return None
    return await finalize_blackjack_round(session, round_obj, participant, mode="stand")


async def _create_runtime_blackjack(flow: _RuntimeFlow, bet: int):
    async with flow.db.session_factory() as session:
        await _ensure_runtime_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat_id)
        if not setting.blackjack_enabled:
            await session.commit()
            await answer_callback_query_safely(flow.update, "黑杰克当前未开启", show_alert=True)
            return None
        points_chat_id = resolve_points_chat_id(setting, flow.chat_id)
        ok, balance = await change_points(
            session, points_chat_id, flow.user.id, amount=-bet,
            txn_type=PointsTxnType.penalty.value, reason="黑杰克下注",
        )
        if not ok:
            await session.commit()
            await answer_callback_query_safely(flow.update, f"积分不足，当前余额 {balance}", show_alert=True)
            return None
        try:
            round_obj, participant = await start_blackjack_round(
                session, flow.chat_id, flow.user.id,
                bet_points=bet, points_chat_id=points_chat_id,
            )
        except ValidationError as exc:
            await session.rollback()
            await answer_callback_query_safely(flow.update, str(exc), show_alert=True)
            return None
        outcome = await _runtime_blackjack_outcome(session, round_obj, participant)
        await session.commit()
    return round_obj, participant, outcome


async def _store_runtime_round(flow: _RuntimeFlow, round_id: int, message_id: int) -> None:
    async with flow.db.session_factory() as session:
        row = await session.execute(select(GameRound).where(GameRound.id == round_id))
        stored_round = row.scalar_one_or_none()
        if stored_round is not None:
            stored_round.announcement_message_id = message_id
        await session.commit()


async def _handle_runtime_blackjack_start(flow: _RuntimeFlow) -> None:
    bet = await _runtime_bet(flow, 4)
    if bet is None:
        return
    result = await _create_runtime_blackjack(flow, bet)
    if result is None:
        return
    round_obj, participant, outcome = result
    sent = await flow.context.bot.send_message(
        chat_id=flow.chat_id,
        text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
        reply_markup=None if outcome else blackjack_round_keyboard(flow.chat_id),
    )
    await _store_runtime_round(flow, round_obj.id, sent.message_id)
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
            session, flow.chat_id, flow.user.id
        )
        if round_obj is None or participant is None:
            await session.commit()
            await answer_callback_query_safely(flow.update, "你当前没有进行中的黑杰克", show_alert=True)
            return
        if flow.action == "hit":
            _, participant, outcome = await blackjack_hit(session, round_obj, participant)
        else:
            outcome = await blackjack_stand(session, round_obj, participant)
        await session.commit()
    await _edit_runtime_blackjack(flow, round_obj, participant, outcome=outcome)
    await show_blackjack_panel(flow.context, flow.db, flow.chat_id)
    await answer_callback_query_safely(flow.update, "已更新当前对局", show_alert=False)


async def _runtime_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return None
    data = CallbackParser.parse(update.callback_query.data or "")
    chat_id = data.get_int_optional(3)
    if chat_id is None:
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
    if flow.game == "k3" and flow.action == "bet":
        await _handle_runtime_k3_bet(flow)
        return
    if flow.game == "bj" and flow.action == "start":
        await _handle_runtime_blackjack_start(flow)
        return
    if flow.game == "bj" and flow.action in {"hit", "stand"}:
        await _handle_runtime_blackjack_action(flow)
        return
    await answer_callback_query_safely(flow.update, "暂不支持该操作", show_alert=True)
