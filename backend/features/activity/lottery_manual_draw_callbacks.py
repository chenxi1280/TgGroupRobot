from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.ui.lottery import (
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.shared.callback_parser import CallbackParser


async def manual_draw_select_prize_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
    get_lottery_fn,
    get_lottery_participants_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 6:
        return
    target_chat_id = cb.get_int(2)
    lottery_id = cb.get_int(3)
    prize_index = cb.get_int(4)
    prize_name = cb.get(5)
    if target_chat_id is None or lottery_id is None or prize_index is None or not prize_name:
        return
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, lottery_id)
        if not lottery or lottery.chat_id != target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        participants = await get_lottery_participants_fn(session, lottery_id)
        user_ids = [p.user_id for p in participants]
        result = await session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))
        users = {u.id: u for u in result.scalars().all()}
        for p in participants:
            p.user_info = users.get(p.user_id)
        await session.commit()
    await handler.message_helper.safe_edit(
        update,
        text=f"🎁 选择中奖人\n\n奖项: {prize_name}\n参与人数: {len(participants)}\n\n请选择中奖者：",
        reply_markup=manual_draw_prize_keyboard(target_chat_id, lottery_id, prize_index, prize_name, participants),
    )


async def manual_draw_select_winner_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
    get_lottery_fn,
    get_user_state_fn,
    set_user_state_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 7:
        return
    target_chat_id = cb.get_int(2)
    lottery_id = cb.get_int(3)
    prize_index = cb.get_int(4)
    winner_user_id = cb.get_int(5)
    prize_name = cb.get(6)
    if target_chat_id is None or lottery_id is None or prize_index is None or winner_user_id is None or not prize_name:
        return
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, lottery_id)
        if not lottery or lottery.chat_id != target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        state = await get_user_state_fn(session, chat.id, user.id)
        if not state or state.state_type != "manual_draw":
            state = await set_user_state_fn(session, chat.id, user.id, "manual_draw", {})
        winners = dict(state.state_data.get("winners", {}))
        result = await session.execute(select(TgUser).where(TgUser.id == winner_user_id))
        winner_user = result.scalar_one_or_none()
        winner_name = (
            winner_user.first_name or winner_user.last_name or winner_user.username or f"用户{winner_user_id}"
            if winner_user
            else "未知用户"
        )
        winners[str(prize_index)] = {"user_id": winner_user_id, "prize_name": prize_name, "name": winner_name}
        state.state_data["winners"] = winners
        state.state_data["lottery_id"] = lottery_id
        state.state_data["target_chat_id"] = target_chat_id
        prizes = lottery.prizes
        await session.commit()
    await handler.message_helper.safe_edit(
        update,
        text=f"✅ 已选择中奖人\n\n奖项: {prize_name}\n中奖人: {winner_name}\n\n请继续选择其他奖项或完成开奖。",
        reply_markup=manual_draw_summary_keyboard_with_winners(target_chat_id, lottery_id, prizes, winners),
    )


async def manual_draw_complete_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
    get_user_state_fn,
    get_lottery_fn,
    create_lottery_winner_fn,
    clear_user_state_fn,
    distribute_lottery_rewards_fn,
    generate_lottery_announcement_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int(2)
    lottery_id = cb.get_int(3, default=0)
    if target_chat_id is None:
        return
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state_fn(session, chat.id, user.id)
        if not state or state.state_type != "manual_draw":
            await handler.message_helper.safe_edit(update, "未找到开奖信息，请重新开始。")
            await session.commit()
            return
        winners = state.state_data.get("winners", {})
        if not winners:
            await handler.message_helper.safe_edit(update, "请先为所有奖项选择中奖人。")
            await session.commit()
            return
        lottery = await get_lottery_fn(session, lottery_id)
        if not lottery or lottery.chat_id != target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        if lottery.status != "pending":
            await handler.message_helper.safe_edit(update, "抽奖已开奖或已取消。")
            await session.commit()
            return
        prize_pool = []
        for prize in lottery.prizes:
            for _ in range(prize.get("quantity", 1)):
                prize_pool.append(prize["name"])
        if len(winners) < len(prize_pool):
            await handler.message_helper.safe_edit(update, f"还有 {len(prize_pool) - len(winners)} 个奖项未选择中奖人，请先完成选择。")
            await session.commit()
            return
        winner_user_ids = [w["user_id"] for w in winners.values()]
        user_result = await session.execute(select(TgUser).where(TgUser.id.in_(winner_user_ids)))
        users = {u.id: u for u in user_result.scalars().all()}
        winners_list = []
        for prize_index, winner_info in winners.items():
            prize_index_int = int(prize_index)
            original_index = prize_index_int // 10
            prize_config = lottery.prizes[original_index]
            points_reward = prize_config.get("points_reward", 0)
            winner = await create_lottery_winner_fn(
                session,
                lottery_id=lottery_id,
                user_id=winner_info["user_id"],
                prize_name=winner_info["prize_name"],
                prize_index=prize_index_int,
            )
            winner.points_reward = points_reward
            winners_list.append(winner)
        await distribute_lottery_rewards_fn(session, lottery, winners_list)
        lottery.status = "completed"
        lottery.drawn_at = dt.datetime.now(dt.UTC)
        announcement = generate_lottery_announcement_fn(lottery, winners_list, users)
        await clear_user_state_fn(session, chat.id, user.id)
        await session.commit()
        await handler.message_helper.safe_edit(update, text=announcement, parse_mode="Markdown")


async def manual_draw_winner_page_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
    get_lottery_fn,
    get_lottery_participants_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 6:
        return
    target_chat_id = cb.get_int(2)
    lottery_id = cb.get_int(3)
    prize_index = cb.get_int(4)
    page = cb.get_int(5)
    if target_chat_id is None or lottery_id is None or prize_index is None or page is None:
        return
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, lottery_id)
        if not lottery or lottery.chat_id != target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        prize_name = lottery.prizes[prize_index // 10]["name"]
        participants = await get_lottery_participants_fn(session, lottery_id)
        user_ids = [p.user_id for p in participants]
        result = await session.execute(select(TgUser).where(TgUser.id.in_(user_ids)))
        users = {u.id: u for u in result.scalars().all()}
        for p in participants:
            p.user_info = users.get(p.user_id)
        await session.commit()
    await handler.message_helper.safe_edit(
        update,
        text=f"🎁 选择中奖人\n\n奖项: {prize_name}\n参与人数: {len(participants)}\n\n请选择中奖者：",
        reply_markup=manual_draw_prize_keyboard(target_chat_id, lottery_id, prize_index, prize_name, participants, page),
    )


async def manual_draw_menu_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
    get_user_state_fn,
    get_lottery_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int(2)
    lottery_id = cb.get_int(3, default=0)
    if target_chat_id is None:
        return
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state_fn(session, chat.id, user.id)
        winners = state.state_data.get("winners", {}) if state else {}
        lottery = await get_lottery_fn(session, lottery_id)
        if not lottery or lottery.chat_id != target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        prizes = lottery.prizes if lottery else []
        await session.commit()
    if winners:
        await handler.message_helper.safe_edit(
            update,
            text=f"📋 手动选择中奖人\n\n抽奖: {lottery.title}\n已选择: {len(winners)}/{len(prizes)} 个奖项",
            reply_markup=manual_draw_summary_keyboard_with_winners(target_chat_id, lottery_id, prizes, winners),
        )
    else:
        await handler.message_helper.safe_edit(
            update,
            text=f"📋 手动选择中奖人\n\n抽奖: {lottery.title}\n请为每个奖项选择中奖人：",
            reply_markup=manual_draw_summary_keyboard(target_chat_id, lottery_id, prizes),
        )
