from __future__ import annotations

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.enums import PointsTxnType
from bot.models.expansion import GameParticipant, GameRound
from bot.services.activity.game_service import (
    blackjack_hit,
    blackjack_stand,
    create_or_join_k3_round,
    finalize_blackjack_round,
    format_blackjack_help,
    format_blackjack_round_text,
    format_k3_help,
    get_active_blackjack_round,
    get_active_k3_round,
    get_or_create_setting,
    parse_blackjack_bet,
    parse_k3_command,
    start_blackjack_round,
    update_setting,
)
from bot.services.activity.points_service import change_points, get_balance
from bot.services.base import ValidationError
from bot.services.core.user_service import ensure_user
from bot.services.shared.publish_service import PublishService
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely


async def _delete_source_if_needed(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delete_mode: str) -> None:
    if delete_mode != "delete":
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        return


def _k3_panel_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for guess, icon in [("大", "⬆️"), ("小", "⬇️"), ("单", "1️⃣"), ("双", "2️⃣"), ("豹子", "🐆")]:
        buttons.append(
            [
                InlineKeyboardButton(f"{icon}{guess}10", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:10"),
                InlineKeyboardButton(f"{icon}{guess}50", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:50"),
                InlineKeyboardButton(f"{icon}{guess}100", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:100"),
            ]
        )
    buttons.append([InlineKeyboardButton("🔄 刷新面板", callback_data=f"gmrun:k3:refresh:{chat_id}")])
    return InlineKeyboardMarkup(buttons)


def _blackjack_panel_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🃏 开局10", callback_data=f"gmrun:bj:start:{chat_id}:10"),
                InlineKeyboardButton("🃏 开局50", callback_data=f"gmrun:bj:start:{chat_id}:50"),
                InlineKeyboardButton("🃏 开局100", callback_data=f"gmrun:bj:start:{chat_id}:100"),
            ],
            [InlineKeyboardButton("🔄 刷新面板", callback_data=f"gmrun:bj:refresh:{chat_id}")],
        ]
    )


def _blackjack_round_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🃏 要牌", callback_data=f"gmrun:bj:hit:{chat_id}"),
                InlineKeyboardButton("✋ 停牌", callback_data=f"gmrun:bj:stand:{chat_id}"),
            ],
            [InlineKeyboardButton("🔄 刷新局面", callback_data=f"gmrun:bj:refresh:{chat_id}")],
        ]
    )


async def _build_k3_panel_text(db: Database, chat_id: int) -> str:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        round_obj = await get_active_k3_round(session, chat_id)
        participant_count = 0
        if round_obj is not None:
            count_result = await session.execute(
                select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id)
            )
            participant_count = int(count_result.scalar() or 0)
        await session.commit()
    lines = [
        "🎲 快3实时面板",
        f"📌 状态：{'✅ 开启' if setting.k3_enabled else '❌ 关闭'}",
        f"💧 抽水比例：{setting.rake_ratio or '0'}",
    ]
    if round_obj is None:
        lines.append("🧾 当前暂无进行中的牌局，点击下方按钮即可下注开局。")
    else:
        lines.extend(
            [
                f"🆔 当前局：#{round_obj.id}",
                f"👥 已下注人数：{participant_count}",
                "⏳ 本局会在 60 秒后自动开奖。",
            ]
        )
    lines.append("🎯 直接点击按钮即可完成下注。")
    return "\n".join(lines)


async def _build_blackjack_panel_text(db: Database, chat_id: int) -> str:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        result = await session.execute(
            select(func.count(GameRound.id)).where(
                GameRound.chat_id == chat_id,
                GameRound.game_type == "blackjack",
                GameRound.status == "player_turn",
            )
        )
        active_count = int(result.scalar() or 0)
        await session.commit()
    lines = [
        "🃏 黑杰克实时面板",
        f"📌 状态：{'✅ 开启' if setting.blackjack_enabled else '❌ 关闭'}",
        f"💧 抽水比例：{setting.rake_ratio or '0'}",
        f"🧾 进行中对局：{active_count}",
        "🎯 点击下方按钮即可按固定积分开局。",
    ]
    return "\n".join(lines)


async def _render_panel_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    message_id: int | None,
) -> int:
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return message_id
        except Exception:
            pass
    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    return sent.message_id


async def _show_k3_panel(context: ContextTypes.DEFAULT_TYPE, db: Database, chat_id: int) -> int:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        existing_message_id = setting.k3_panel_message_id
        await session.commit()
    text = await _build_k3_panel_text(db, chat_id)
    message_id = await _render_panel_message(context, chat_id, text, _k3_panel_keyboard(chat_id), existing_message_id)
    async with db.session_factory() as session:
        await update_setting(session, chat_id, k3_panel_message_id=message_id)
        await session.commit()
    return message_id


async def _show_blackjack_panel(context: ContextTypes.DEFAULT_TYPE, db: Database, chat_id: int) -> int:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        existing_message_id = setting.blackjack_panel_message_id
        await session.commit()
    text = await _build_blackjack_panel_text(db, chat_id)
    message_id = await _render_panel_message(context, chat_id, text, _blackjack_panel_keyboard(chat_id), existing_message_id)
    async with db.session_factory() as session:
        await update_setting(session, chat_id, blackjack_panel_message_id=message_id)
        await session.commit()
    return message_id


async def game_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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

    if text == "快3":
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await _show_k3_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=format_k3_help(setting.k3_enabled, setting.rake_ratio),
            reply_to_message_id=update.effective_message.message_id,
        )
        await _delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    parsed_k3 = parse_k3_command(text)
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
                    text="🎮 快3当前未开启。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            balance = await get_balance(session, chat.id, user.id)
            if balance < bet_points:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"⚠️ 积分不足，当前余额 {balance}。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            await change_points(session, chat.id, user.id, -bet_points, PointsTxnType.penalty.value, reason="快3下注")
            round_obj, _participant = await create_or_join_k3_round(session, chat.id, user.id, guess, bet_points)
            count_result = await session.execute(
                select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id)
            )
            participant_count = int(count_result.scalar() or 0)
            await session.commit()
        await _show_k3_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=(
                f"🎲 快3下注成功\n"
                f"🎯 竞猜：{guess}\n"
                f"💰 下注：{bet_points}\n"
                f"👥 本局人数：{participant_count}\n"
                "⏳ 本局将在 60 秒后自动开奖。"
            ),
            reply_to_message_id=update.effective_message.message_id,
        )
        await _delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    if text == "黑杰克":
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat.id)
            await session.commit()
        await _show_blackjack_panel(context, db, chat.id)
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=format_blackjack_help(setting.blackjack_enabled, setting.rake_ratio),
            reply_to_message_id=update.effective_message.message_id,
        )
        await _delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    blackjack_bet = parse_blackjack_bet(text)
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
            balance = await get_balance(session, chat.id, user.id)
            if balance < blackjack_bet:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"⚠️ 积分不足，当前余额 {balance}。",
                    reply_to_message_id=update.effective_message.message_id,
                )
                return True
            await change_points(session, chat.id, user.id, -blackjack_bet, PointsTxnType.penalty.value, reason="黑杰克下注")
            try:
                round_obj, participant = await start_blackjack_round(session, chat.id, user.id, blackjack_bet)
            except ValidationError as exc:
                await session.rollback()
                await PublishService.reply(context, chat_id=chat.id, text=f"⚠️ {exc}", reply_to_message_id=update.effective_message.message_id)
                return True
            outcome = None
            if len((participant.choice_data or {}).get("player_cards") or []) == 2:
                from bot.services.activity.game_service import blackjack_total
                if blackjack_total(participant.choice_data["player_cards"]) == 21:
                    outcome = await finalize_blackjack_round(session, round_obj, participant, "stand")
            await session.commit()
        round_text = format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome)
        sent = await context.bot.send_message(
            chat_id=chat.id,
            text=round_text,
            reply_markup=None if outcome else _blackjack_round_keyboard(chat.id),
            reply_to_message_id=update.effective_message.message_id,
        )
        async with db.session_factory() as session:
            stmt = select(GameRound).where(GameRound.id == round_obj.id)
            row = await session.execute(stmt)
            stored_round = row.scalar_one_or_none()
            if stored_round is not None:
                stored_round.announcement_message_id = sent.message_id
            await session.commit()
        await _show_blackjack_panel(context, db, chat.id)
        await _delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
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
                    reply_markup=None if outcome else _blackjack_round_keyboard(chat.id),
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
        await _show_blackjack_panel(context, db, chat.id)
        await _delete_source_if_needed(context, chat.id, update.effective_message.message_id, setting.delete_game_message_mode)
        return True

    return False


async def game_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    db: Database = context.application.bot_data["db"]
    user = update.effective_user

    if game == "k3" and action == "refresh":
        await _show_k3_panel(context, db, chat_id)
        await answer_callback_query_safely(update, "已刷新快3面板")
        return
    if game == "bj" and action == "refresh":
        await _show_blackjack_panel(context, db, chat_id)
        async with db.session_factory() as session:
            round_obj, participant = await get_active_blackjack_round(session, chat_id, user.id)
            await session.commit()
        if round_obj and participant and round_obj.announcement_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=round_obj.announcement_message_id,
                    text=format_blackjack_round_text(participant),
                    reply_markup=_blackjack_round_keyboard(chat_id),
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
            count_result = await session.execute(select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id))
            participant_count = int(count_result.scalar() or 0)
            await session.commit()
        await _show_k3_panel(context, db, chat_id)
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
                from bot.services.activity.game_service import blackjack_total
                if blackjack_total(participant.choice_data["player_cards"]) == 21:
                    outcome = await finalize_blackjack_round(session, round_obj, participant, "stand")
            await session.commit()
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome),
            reply_markup=None if outcome else _blackjack_round_keyboard(chat_id),
        )
        async with db.session_factory() as session:
            stmt = select(GameRound).where(GameRound.id == round_obj.id)
            row = await session.execute(stmt)
            stored_round = row.scalar_one_or_none()
            if stored_round is not None:
                stored_round.announcement_message_id = sent.message_id
            await session.commit()
        await _show_blackjack_panel(context, db, chat_id)
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
                    reply_markup=None if outcome else _blackjack_round_keyboard(chat_id),
                )
            except Exception:
                pass
        await _show_blackjack_panel(context, db, chat_id)
        await answer_callback_query_safely(update, "已更新当前对局")
        return

    await answer_callback_query_safely(update, "暂不支持该操作", show_alert=True)
