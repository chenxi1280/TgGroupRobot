from __future__ import annotations

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
    get_active_blackjack_round,
    get_or_create_setting,
    start_blackjack_round,
)
from backend.features.points.services.points_service import change_points, get_balance
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user


async def handle_game_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    data = CallbackParser.parse(query.data or "")
    game = data.get(1)
    action = data.get(2)
    chat_id = data.get_int_optional(3)
    if chat_id is None:
        await answer_callback_query_safely(update, "参数错误", show_alert=True)
        return
    await query.answer()
    mark_callback_query_answered(update)
    db: Database = context.application.bot_data["db"]
    user = update.effective_user

    if game == "k3" and action == "refresh":
        await show_k3_panel(context, db, chat_id)
        await answer_callback_query_safely(update, "已刷新快3面板")
        return
    if game == "bj" and action == "refresh":
        await show_blackjack_panel(context, db, chat_id)
        async with db.session_factory() as session:
            round_obj, participant = await get_active_blackjack_round(session, chat_id, user.id)
            await session.commit()
        if round_obj and participant and round_obj.announcement_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=round_obj.announcement_message_id,
                    text=format_blackjack_round_text(participant),
                    reply_markup=blackjack_round_keyboard(chat_id),
                )
            except Exception:
                pass
        await answer_callback_query_safely(update, "已刷新黑杰克面板")
        return

    if game == "k3" and action == "bet":
        guess = data.get(4) or ""
        try:
            bet_points = int(data.get(5, "0") or "0")
        except ValueError:
            await answer_callback_query_safely(update, "下注参数无效", show_alert=True)
            return
        async with db.session_factory() as session:
            await ensure_user(session, user.id, user.username, user.first_name, user.last_name, user.language_code)
            setting = await get_or_create_setting(session, chat_id)
            if not setting.k3_enabled:
                await session.commit()
                await answer_callback_query_safely(update, "快3当前未开启", show_alert=True)
                return
            balance = await get_balance(session, chat_id, user.id)
            if balance < bet_points:
                await session.commit()
                await answer_callback_query_safely(update, f"积分不足，当前余额 {balance}", show_alert=True)
                return
            try:
                await change_points(session, chat_id, user.id, -bet_points, PointsTxnType.penalty.value, reason="快3下注")
                round_obj, _participant = await create_or_join_k3_round(session, chat_id, user.id, guess, bet_points)
            except ValidationError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            count_result = await session.execute(
                select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id)
            )
            participant_count = int(count_result.scalar() or 0)
            await session.commit()
        await show_k3_panel(context, db, chat_id)
        await answer_callback_query_safely(update, f"下注成功：{guess} {bet_points}，本局 {participant_count} 人")
        return

    if game == "bj" and action == "start":
        try:
            bet_points = int(data.get(4, "0") or "0")
        except ValueError:
            await answer_callback_query_safely(update, "下注参数无效", show_alert=True)
            return
        async with db.session_factory() as session:
            await ensure_user(session, user.id, user.username, user.first_name, user.last_name, user.language_code)
            setting = await get_or_create_setting(session, chat_id)
            if not setting.blackjack_enabled:
                await session.commit()
                await answer_callback_query_safely(update, "黑杰克当前未开启", show_alert=True)
                return
            balance = await get_balance(session, chat_id, user.id)
            if balance < bet_points:
                await session.commit()
                await answer_callback_query_safely(update, f"积分不足，当前余额 {balance}", show_alert=True)
                return
            await change_points(session, chat_id, user.id, -bet_points, PointsTxnType.penalty.value, reason="黑杰克下注")
            try:
                round_obj, participant = await start_blackjack_round(session, chat_id, user.id, bet_points)
            except ValidationError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            outcome = None
            if len((participant.choice_data or {}).get("player_cards") or []) == 2:
                from backend.features.activity.services.game_service import blackjack_total
                if blackjack_total(participant.choice_data["player_cards"]) == 21:
                    outcome = await finalize_blackjack_round(session, round_obj, participant, "stand")
            await session.commit()
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
            reply_markup=None if outcome else blackjack_round_keyboard(chat_id),
        )
        async with db.session_factory() as session:
            stmt = select(GameRound).where(GameRound.id == round_obj.id)
            row = await session.execute(stmt)
            stored_round = row.scalar_one_or_none()
            if stored_round is not None:
                stored_round.announcement_message_id = sent.message_id
            await session.commit()
        await show_blackjack_panel(context, db, chat_id)
        await answer_callback_query_safely(update, f"黑杰克开局成功：{bet_points}")
        return

    if game == "bj" and action in {"hit", "stand"}:
        async with db.session_factory() as session:
            round_obj, participant = await get_active_blackjack_round(session, chat_id, user.id)
            if round_obj is None or participant is None:
                await session.commit()
                await answer_callback_query_safely(update, "你当前没有进行中的黑杰克", show_alert=True)
                return
            if action == "hit":
                _, participant, outcome = await blackjack_hit(session, round_obj, participant)
            else:
                outcome = await blackjack_stand(session, round_obj, participant)
            await session.commit()
        if round_obj.announcement_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=round_obj.announcement_message_id,
                    text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
                    reply_markup=None if outcome else blackjack_round_keyboard(chat_id),
                )
            except Exception:
                pass
        await show_blackjack_panel(context, db, chat_id)
        await answer_callback_query_safely(update, "已更新当前对局")
        return

    await answer_callback_query_safely(update, "暂不支持该操作", show_alert=True)
