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
    finalize_blackjack_round,
    format_blackjack_help,
    format_blackjack_round_text,
    format_k3_help,
    get_active_k3_round,
    get_active_blackjack_round,
    get_or_create_setting,
    get_round_points_chat_id,
    k3_guess_label,
    parse_blackjack_bet,
    parse_k3_command,
    resolve_points_chat_id,
    start_blackjack_round,
    create_or_join_k3_round,
)
from backend.features.points.services.points_service import change_points
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService
from backend.shared.services.user_service import ensure_user


async def delete_source_if_needed(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    delete_mode: str,
) -> None:
    if delete_mode != "delete":
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        return


async def build_user_game_stats(session, chat_id: int, user_id: int, game_type: str, title: str) -> str:
    result = await session.execute(
        select(
            GameParticipant.status,
            func.count(GameParticipant.id),
            func.coalesce(func.sum(GameParticipant.bet_points), 0),
            func.coalesce(func.sum(GameParticipant.payout_points), 0),
        )
        .join(GameRound, GameRound.id == GameParticipant.round_id)
        .where(
            GameRound.chat_id == chat_id,
            GameRound.game_type == game_type,
            GameParticipant.user_id == user_id,
        )
        .group_by(GameParticipant.status)
    )
    rows = result.all()
    status_counts = {str(status): int(count or 0) for status, count, _bet, _payout in rows}
    total_bet = sum(int(bet or 0) for _status, _count, bet, _payout in rows)
    total_payout = sum(int(payout or 0) for _status, _count, _bet, payout in rows)
    total_rounds = sum(status_counts.values())
    return "\n".join(
        [
            f"{title}统计",
            f"总局数：{total_rounds}",
            f"获胜：{status_counts.get('won', 0)}",
            f"失败：{status_counts.get('lost', 0)}",
            f"平局：{status_counts.get('push', 0)}",
            f"进行中：{status_counts.get('active', 0)}",
            f"累计下注：{total_bet}",
            f"累计返奖：{total_payout}",
            f"净结果：{total_payout - total_bet}",
        ]
    )


async def handle_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return False
    if update.effective_chat.type == "private":
        return False

    chat = update.effective_chat
    user = update.effective_user
    text = (update.effective_message.text or "").strip()
    if not text:
        return False

    db: Database = context.application.bot_data["db"]

    if text in {"快3", "快三"}:
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await show_k3_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=format_k3_help(setting.k3_enabled, setting.rake_ratio),
            reply_to_message_id=update.effective_message.message_id,
        )
        await delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    if text in {"快3规则", "快三规则"}:
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=format_k3_help(setting.k3_enabled, setting.rake_ratio),
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    if text in {"快3统计", "快三统计"}:
        async with db.session_factory() as session:
            text_reply = await build_user_game_stats(session, chat.id, user.id, "k3", "🎲 快三")
            await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=text_reply,
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    try:
        parsed_k3 = parse_k3_command(text)
    except ValidationError as exc:
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=f"⚠️ {exc}",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True
    if parsed_k3 is not None:
        guess, bet_points = parsed_k3
        async with db.session_factory() as session:
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            setting = await get_or_create_setting(session, chat.id)
            if not setting.k3_enabled:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="🎮 快三当前未开启。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            active_round = await get_active_k3_round(session, chat.id)
            points_chat_id = (
                get_round_points_chat_id(active_round, resolve_points_chat_id(setting, chat.id))
                if active_round is not None
                else resolve_points_chat_id(setting, chat.id)
            )
            ok, balance = await change_points(session, points_chat_id, user.id, -bet_points, PointsTxnType.penalty.value, reason="快三下注")
            if not ok:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"⚠️ 积分不足，当前余额 {balance}。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            try:
                round_obj, _participant = await create_or_join_k3_round(
                    session,
                    chat.id,
                    user.id,
                    guess,
                    bet_points,
                    points_chat_id=points_chat_id,
                )
            except ValidationError as exc:
                await session.rollback()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"⚠️ {exc}",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            count_result = await session.execute(
                select(GameParticipant.id).where(GameParticipant.round_id == round_obj.id)
            )
            participant_count = len(count_result.scalars().all())
            await session.commit()
        await show_k3_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=(
                f"🎲 快三下注成功\n"
                f"🎯 竞猜：{k3_guess_label(guess)}\n"
                f"💰 下注：{bet_points}\n"
                f"👥 本局人数：{participant_count}\n"
                "⏳ 本局将在 60 秒后自动开奖。"
            ),
            reply_to_message_id=update.effective_message.message_id,
        )
        await delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    if text == "黑杰克":
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await show_blackjack_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=format_blackjack_help(setting.blackjack_enabled, setting.rake_ratio),
            reply_to_message_id=update.effective_message.message_id,
        )
        await delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    if text == "黑杰克规则":
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=(
                f"{format_blackjack_help(setting.blackjack_enabled, setting.rake_ratio)}\n"
                "规则：A 可按 1 或 11 计，J/Q/K 按 10 计；超过 21 点爆牌；停牌后庄家补到 17 点以上再比点数。"
            ),
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    if text == "黑杰克统计":
        async with db.session_factory() as session:
            text_reply = await build_user_game_stats(session, chat.id, user.id, "blackjack", "🃏 黑杰克")
            await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=text_reply,
            reply_to_message_id=update.effective_message.message_id,
        )
        return True

    try:
        blackjack_bet = parse_blackjack_bet(text)
    except ValidationError as exc:
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=f"⚠️ {exc}",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True
    if blackjack_bet is not None:
        async with db.session_factory() as session:
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            setting = await get_or_create_setting(session, chat.id)
            if not setting.blackjack_enabled:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="🎮 黑杰克当前未开启。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            points_chat_id = resolve_points_chat_id(setting, chat.id)
            ok, balance = await change_points(session, points_chat_id, user.id, -blackjack_bet, PointsTxnType.penalty.value, reason="黑杰克下注")
            if not ok:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"⚠️ 积分不足，当前余额 {balance}。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            try:
                round_obj, participant = await start_blackjack_round(
                    session,
                    chat.id,
                    user.id,
                    blackjack_bet,
                    points_chat_id=points_chat_id,
                )
            except ValidationError as exc:
                await session.rollback()
                await PublishService.reply(context, chat_id=chat.id, text=f"⚠️ {exc}", reply_to_message_id=update.effective_message.message_id)
                return True
            outcome = None
            if len((participant.choice_data or {}).get("player_cards") or []) == 2:
                from backend.features.activity.services.game_service import blackjack_total
                if blackjack_total(participant.choice_data["player_cards"]) == 21:
                    outcome = await finalize_blackjack_round(session, round_obj, participant, "stand")
            await session.commit()
        round_text = format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome)
        sent = await context.bot.send_message(
            chat_id=chat.id,
            text=round_text,
            reply_markup=None if outcome else blackjack_round_keyboard(chat.id),
            reply_to_message_id=update.effective_message.message_id,
        )
        async with db.session_factory() as session:
            stmt = select(GameRound).where(GameRound.id == round_obj.id)
            row = await session.execute(stmt)
            stored_round = row.scalar_one_or_none()
            if stored_round is not None:
                stored_round.announcement_message_id = sent.message_id
            await session.commit()
        await show_blackjack_panel(context, db, chat.id)
        await delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    if text in {"要牌", "停牌"}:
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            round_obj, participant = await get_active_blackjack_round(session, chat.id, user.id)
            if round_obj is None or participant is None:
                await session.commit()
                return False
            outcome = None
            if text == "要牌":
                _, participant, outcome = await blackjack_hit(session, round_obj, participant)
            else:
                outcome = await blackjack_stand(session, round_obj, participant)
            await session.commit()
        if round_obj.announcement_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=round_obj.announcement_message_id,
                    text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
                    reply_markup=None if outcome else blackjack_round_keyboard(chat.id),
                )
            except Exception:
                pass
        else:
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
                reply_to_message_id=update.effective_message.message_id,
            )
        await show_blackjack_panel(context, db, chat.id)
        await delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    return False
