from __future__ import annotations

import structlog
from dataclasses import dataclass
from sqlalchemy import Integer, func, select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.game_notice_delivery import deliver_game_notices
from backend.features.activity.game_web_notifications import queue_group_blackjack
from backend.features.activity.game_panels import (
    blackjack_round_keyboard,
    k3_fee_confirmation,
    show_blackjack_panel,
    show_k3_panel,
)
from backend.features.activity.room_games.fees import fee_settings
from backend.features.activity.services.game_service import (
    blackjack_hit,
    blackjack_stand,
    place_blackjack_bet,
    format_blackjack_help,
    format_blackjack_round_text,
    format_k3_help,
    get_active_blackjack_round,
    get_or_create_setting,
    k3_guess_label,
    parse_blackjack_bet,
    parse_k3_command,
    create_or_join_k3_round,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService
from backend.shared.services.user_service import ensure_user


log = structlog.get_logger(__name__)


async def delete_source_if_needed(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    *, delete_mode: str,
) -> None:
    if delete_mode != "delete":
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        log.warning("game_delete_source_failed", chat_id=chat_id, message_id=message_id, error=str(exc))
        return


async def build_user_game_stats(session, chat_id: int, user_id: int, *, game_type: str, title: str) -> str:
    result = await session.execute(
        select(
            GameParticipant.status,
            func.count(GameParticipant.id),
            func.coalesce(func.sum(GameParticipant.bet_points), 0),
            func.coalesce(func.sum(GameParticipant.payout_points), 0),
            func.coalesce(func.sum(GameParticipant.choice_data["fee"].astext.cast(Integer)), 0),
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
    status_counts = {str(status): int(count or 0) for status, count, _bet, _payout, _fee in rows}
    total_bet = sum(int(bet or 0) for _status, _count, bet, _payout, _fee in rows)
    total_payout = sum(int(payout or 0) for _status, _count, _bet, payout, _fee in rows)
    total_fee = sum(int(fee or 0) for _, _, _, _, fee in rows)
    total_rounds = sum(status_counts.values())
    return "\n".join(
        [
            f"{title}统计", f"总局数：{total_rounds}",
            f"获胜：{status_counts.get('won', 0)}", f"失败：{status_counts.get('lost', 0)}",
            f"平局：{status_counts.get('push', 0)}", f"进行中：{status_counts.get('active', 0)}",
            f"累计下注：{total_bet}", f"累计返奖：{total_payout}",
            f"净结果：{total_payout - total_bet - total_fee}",
        ]
    )


@dataclass(frozen=True)
class _GameMessageFlow:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    db: Database
    chat: object
    user: object
    message: object
    text: str


async def _reply_game(flow: _GameMessageFlow, text: str) -> None:
    await PublishService.reply(
        flow.context, chat_id=flow.chat.id, text=text,
        reply_to_message_id=flow.message.message_id,
    )


async def _load_game_setting(flow: _GameMessageFlow):
    async with flow.db.session_factory() as session:
        setting = await get_or_create_setting(session, flow.chat.id)
        await session.commit()
    return setting


async def _handle_k3_info(flow: _GameMessageFlow) -> bool:
    if flow.text in {"快3", "快三"}:
        setting = await _load_game_setting(flow)
        await show_k3_panel(flow.context, flow.db, flow.chat.id)
        await _reply_game(flow, format_k3_help(setting.k3_enabled, setting.rake_ratio))
        await delete_source_if_needed(
            flow.context, flow.chat.id, flow.message.message_id,
            delete_mode=setting.delete_game_message_mode,
        )
        return True
    if flow.text in {"快3规则", "快三规则"}:
        setting = await _load_game_setting(flow)
        await _reply_game(flow, format_k3_help(setting.k3_enabled, setting.rake_ratio))
        return True
    if flow.text not in {"快3统计", "快三统计"}:
        return False
    async with flow.db.session_factory() as session:
        reply = await build_user_game_stats(
            session, flow.chat.id, flow.user.id, game_type="k3", title="🎲 快三"
        )
        await session.commit()
    await _reply_game(flow, reply)
    return True


async def _handle_blackjack_info(flow: _GameMessageFlow) -> bool:
    if flow.text == "黑杰克":
        setting = await _load_game_setting(flow)
        await show_blackjack_panel(flow.context, flow.db, flow.chat.id)
        await _reply_game(flow, format_blackjack_help(setting.blackjack_enabled, setting.rake_ratio))
        await delete_source_if_needed(
            flow.context, flow.chat.id, flow.message.message_id,
            delete_mode=setting.delete_game_message_mode,
        )
        return True
    if flow.text == "黑杰克规则":
        setting = await _load_game_setting(flow)
        rules = "规则：A 可按 1 或 11 计，J/Q/K 按 10 计；超过 21 点爆牌；停牌后庄家补到 17 点以上再比点数。"
        await _reply_game(flow, f"{format_blackjack_help(setting.blackjack_enabled, setting.rake_ratio)}\n{rules}")
        return True
    if flow.text != "黑杰克统计":
        return False
    async with flow.db.session_factory() as session:
        reply = await build_user_game_stats(
            session, flow.chat.id, flow.user.id, game_type="blackjack", title="🃏 黑杰克"
        )
        await session.commit()
    await _reply_game(flow, reply)
    return True


async def _parse_k3_bet(flow: _GameMessageFlow):
    try:
        parsed = parse_k3_command(flow.text)
    except ValidationError as exc:
        await _reply_game(flow, f"⚠️ {exc}")
        return True, None
    if parsed is None and flow.text.startswith(("快3", "快三")):
        await _reply_game(flow, "⚠️ 快三格式错误，请发送：`快三 大 100`。可选：大/小/单/双/豹子/对子/半顺/三连/杂六。")
        return True, None
    return False, parsed


async def _ensure_game_user(session, user) -> None:
    await ensure_user(
        session, user_id=user.id, username=user.username,
        first_name=user.first_name, last_name=user.last_name,
        language_code=user.language_code,
    )


async def _create_k3_bet(flow: _GameMessageFlow, parsed):
    guess, bet_points = parsed
    async with flow.db.session_factory() as session:
        await _ensure_game_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat.id)
        if not setting.k3_enabled:
            await session.commit()
            await _reply_game(flow, "🎮 快三当前未开启。")
            return None
        fee = (await fee_settings(session)).k3
        if fee:
            text, keyboard = k3_fee_confirmation(flow.chat.id, flow.user.id, guess=guess, bet=bet_points, fee=fee)
            await session.rollback()
            await PublishService.reply(flow.context, chat_id=flow.chat.id, text=text,
                                       reply_to_message_id=flow.message.message_id, reply_markup=keyboard)
            return None
        try:
            round_obj, _ = await create_or_join_k3_round(
                session, flow.chat.id, flow.user.id, guess=guess,
                bet_points=bet_points,
            )
        except ValidationError as exc:
            await session.rollback()
            await _reply_game(flow, f"⚠️ {exc}")
            return None
        rows = await session.execute(select(GameParticipant.id).where(GameParticipant.round_id == round_obj.id))
        participant_count = len(rows.scalars().all())
        await session.commit()
    return setting, guess, bet_points, participant_count


async def _handle_k3_bet(flow: _GameMessageFlow, parsed) -> bool:
    result = await _create_k3_bet(flow, parsed)
    if result is None:
        return True
    setting, guess, bet_points, participant_count = result
    await show_k3_panel(flow.context, flow.db, flow.chat.id)
    await _reply_game(
        flow, f"🎲 快三下注成功\n🎯 竞猜：{k3_guess_label(guess)}\n"
        f"💰 下注：{bet_points}\n👥 本局人数：{participant_count}\n⏳ 本局将在 60 秒后自动开奖。",
    )
    await delete_source_if_needed(
        flow.context, flow.chat.id, flow.message.message_id,
        delete_mode=setting.delete_game_message_mode,
    )
    return True


async def _parse_blackjack_bet(flow: _GameMessageFlow):
    try:
        bet = parse_blackjack_bet(flow.text)
    except ValidationError as exc:
        await _reply_game(flow, f"⚠️ {exc}")
        return True, None
    if bet is None and flow.text.startswith("黑杰克"):
        await _reply_game(flow, "⚠️ 黑杰克格式错误，请发送：`黑杰克 100`。开局后可发送“要牌”或“停牌”。")
        return True, None
    return False, bet


async def _create_blackjack_bet(flow: _GameMessageFlow, bet: int):
    async with flow.db.session_factory() as session:
        await _ensure_game_user(session, flow.user)
        setting = await get_or_create_setting(session, flow.chat.id)
        await session.refresh(setting, with_for_update=True)
        if not setting.blackjack_enabled:
            await session.commit()
            await _reply_game(flow, "🎮 黑杰克当前未开启。")
            return None
        try:
            round_obj, participant, outcome = await place_blackjack_bet(session, setting, flow.user.id, bet=bet)
        except ValidationError as exc:
            await session.rollback()
            await _reply_game(flow, f"⚠️ {exc}")
            return None
        notice = queue_group_blackjack(
            session, round_obj, participant, outcome=outcome, opening=True, reply_to=flow.message.message_id,
            keyboard=None if outcome else blackjack_round_keyboard(flow.chat.id),
        )
        await session.flush()
        notice_id = notice.id
        await session.commit()
    return setting, notice_id


async def _handle_blackjack_bet(flow: _GameMessageFlow, bet: int) -> bool:
    result = await _create_blackjack_bet(flow, bet)
    if result is None:
        return True
    setting, notice_id = result
    await deliver_game_notices(flow.db, flow.context.bot, [notice_id])
    await show_blackjack_panel(flow.context, flow.db, flow.chat.id)
    await delete_source_if_needed(
        flow.context, flow.chat.id, flow.message.message_id,
        delete_mode=setting.delete_game_message_mode,
    )
    return True


async def _publish_blackjack_action(
    flow: _GameMessageFlow, round_obj, participant, *, outcome
) -> None:
    text = format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome)
    keyboard = None if outcome else blackjack_round_keyboard(flow.chat.id)
    if not round_obj.announcement_message_id:
        await _reply_game(flow, text)
        return
    try:
        await flow.context.bot.edit_message_text(
            chat_id=flow.chat.id, message_id=round_obj.announcement_message_id,
            text=text, reply_markup=keyboard,
        )
    except Exception as exc:
        log.warning(
            "blackjack_round_edit_failed", chat_id=flow.chat.id,
            message_id=round_obj.announcement_message_id,
            user_id=flow.user.id, error=str(exc),
        )
        await _reply_game(flow, text)


async def _handle_blackjack_action(flow: _GameMessageFlow) -> bool:
    if flow.text not in {"要牌", "停牌"}:
        return False
    async with flow.db.session_factory() as session:
        setting = await get_or_create_setting(session, flow.chat.id)
        round_obj, participant = await get_active_blackjack_round(session, flow.chat.id, flow.user.id, lock=True)
        if round_obj is None or participant is None:
            await session.commit()
            return False
        if flow.text == "要牌":
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
        await _publish_blackjack_action(flow, round_obj, participant, outcome=outcome)
    await show_blackjack_panel(flow.context, flow.db, flow.chat.id)
    await delete_source_if_needed(
        flow.context, flow.chat.id, flow.message.message_id,
        delete_mode=setting.delete_game_message_mode,
    )
    return True


def _game_message_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None or chat.type == "private":
        return None
    text = (message.text or "").strip()
    if not text:
        return None
    db: Database = context.application.bot_data["db"]
    return _GameMessageFlow(
        update=update, context=context, db=db, chat=chat,
        user=user, message=message, text=text,
    )


async def handle_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    flow = _game_message_flow(update, context)
    if flow is None:
        return False
    if await _handle_k3_info(flow) or await _handle_blackjack_info(flow):
        return True
    handled, k3_bet = await _parse_k3_bet(flow)
    if handled:
        return True
    if k3_bet is not None:
        return await _handle_k3_bet(flow, k3_bet)
    handled, blackjack_bet = await _parse_blackjack_bet(flow)
    if handled:
        return True
    if blackjack_bet is not None:
        return await _handle_blackjack_bet(flow, blackjack_bet)
    return await _handle_blackjack_action(flow)
