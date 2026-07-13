from __future__ import annotations


from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.ui.lottery import (
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.platform.db.runtime.session import Database
from backend.shared.callback_parser import CallbackParser
from backend.features.activity.lottery_manual_draw_support import (
    _complete_manual_draw,
    _eligible_participants,
    _is_authorized,
    _load_manual_menu,
    _parse_prize_selection,
    _record_selected_winner,
)


def _parse_lottery_callback(callback_data: str) -> tuple[int, int] | None:
    cb = CallbackParser.parse(callback_data)
    target_chat_id = cb.get_int(2)
    if target_chat_id is None:
        return None
    return target_chat_id, cb.get_int(3, default=0)


async def _render_selected_winner(
    update: Update,
    handler,
    selection,
    *,
    winner_name: str,
    winners: dict,
    prizes: list,
) -> None:
    keyboard = manual_draw_summary_keyboard_with_winners(
        selection.target_chat_id,
        selection.lottery_id,
        prizes,
        winners=winners,
    )
    await handler.message_helper.safe_edit(
        update,
        text=f"✅ 已选择中奖人\n\n奖项: {selection.prize_name}\n中奖人: {winner_name}\n\n请继续选择其他奖项或完成开奖。",
        reply_markup=keyboard,
    )


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
    await update.callback_query.answer()
    selection = _parse_prize_selection(update.callback_query.data or "", mode="prize")
    if selection is None:
        return
    if not await _is_authorized(
        update,
        context,
        handler,
        target_chat_id=selection.target_chat_id,
        is_user_admin_fn=is_user_admin_fn,
    ):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, selection.lottery_id)
        if not lottery or lottery.chat_id != selection.target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        participants = await _eligible_participants(
            session,
            context,
            lottery,
            get_lottery_participants_fn=get_lottery_participants_fn,
        )
        await session.commit()
    await handler.message_helper.safe_edit(
        update,
        text=f"🎁 选择中奖人\n\n奖项: {selection.prize_name}\n参与人数: {len(participants)}\n\n请选择中奖者：",
        reply_markup=manual_draw_prize_keyboard(
            selection.target_chat_id,
            selection.lottery_id,
            selection.prize_index,
            prize_name=selection.prize_name,
            participants=participants,
        ),
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
    await update.callback_query.answer()
    selection = _parse_prize_selection(update.callback_query.data or "", mode="winner")
    if selection is None:
        return
    if not await _is_authorized(
        update,
        context,
        handler,
        target_chat_id=selection.target_chat_id,
        is_user_admin_fn=is_user_admin_fn,
    ):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, selection.lottery_id)
        if not lottery or lottery.chat_id != selection.target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        winner_name, winners = await _record_selected_winner(
            session,
            selection,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            lottery=lottery,
            get_user_state_fn=get_user_state_fn,
            set_user_state_fn=set_user_state_fn,
        )
        prizes = lottery.prizes
        await session.commit()
    await _render_selected_winner(
        update,
        handler,
        selection,
        winner_name=winner_name,
        winners=winners,
        prizes=prizes,
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
    await update.callback_query.answer()
    callback_key = _parse_lottery_callback(update.callback_query.data or "")
    if callback_key is None:
        return
    target_chat_id, lottery_id = callback_key
    if not await _is_authorized(
        update,
        context,
        handler,
        target_chat_id=target_chat_id,
        is_user_admin_fn=is_user_admin_fn,
    ):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        announcement, error = await _complete_manual_draw(
            session,
            context,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            target_chat_id=target_chat_id,
            lottery_id=lottery_id,
            get_user_state_fn=get_user_state_fn,
            get_lottery_fn=get_lottery_fn,
            create_lottery_winner_fn=create_lottery_winner_fn,
            clear_user_state_fn=clear_user_state_fn,
            distribute_lottery_rewards_fn=distribute_lottery_rewards_fn,
            generate_lottery_announcement_fn=generate_lottery_announcement_fn,
        )
        if error:
            await handler.message_helper.safe_edit(update, error)
            await session.commit()
            return
        await handler.message_helper.safe_edit(update, text=announcement, parse_mode="HTML")
        await session.commit()


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
    await update.callback_query.answer()
    selection = _parse_prize_selection(update.callback_query.data or "", mode="page")
    if selection is None:
        return
    if not await _is_authorized(
        update,
        context,
        handler,
        target_chat_id=selection.target_chat_id,
        is_user_admin_fn=is_user_admin_fn,
    ):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery_fn(session, selection.lottery_id)
        if not lottery or lottery.chat_id != selection.target_chat_id:
            await handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return
        prize_name = lottery.prizes[selection.prize_index // 10]["name"]
        participants = await _eligible_participants(
            session,
            context,
            lottery,
            get_lottery_participants_fn=get_lottery_participants_fn,
        )
        await session.commit()
    await handler.message_helper.safe_edit(
        update,
        text=f"🎁 选择中奖人\n\n奖项: {prize_name}\n参与人数: {len(participants)}\n\n请选择中奖者：",
        reply_markup=manual_draw_prize_keyboard(
            selection.target_chat_id,
            selection.lottery_id,
            selection.prize_index,
            prize_name=prize_name,
            participants=participants,
            page=selection.page,
        ),
    )


async def _render_manual_draw_menu(
    update: Update,
    handler,
    lottery,
    *,
    target_chat_id: int,
    lottery_id: int,
    winners: dict,
) -> None:
    prizes = lottery.prizes
    text = f"📋 手动选择中奖人\n\n抽奖: {lottery.title}\n"
    if winners:
        text += f"已选择: {len(winners)}/{len(prizes)} 个奖项"
        keyboard = manual_draw_summary_keyboard_with_winners(
            target_chat_id,
            lottery_id,
            prizes,
            winners=winners,
        )
    else:
        text += "请为每个奖项选择中奖人："
        keyboard = manual_draw_summary_keyboard(target_chat_id, lottery_id, prizes)
    await handler.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


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
    await update.callback_query.answer()
    chat = update.effective_chat
    user = update.effective_user
    callback_key = _parse_lottery_callback(update.callback_query.data or "")
    if callback_key is None:
        return
    target_chat_id, lottery_id = callback_key
    if not await _is_authorized(
        update,
        context,
        handler,
        target_chat_id=target_chat_id,
        is_user_admin_fn=is_user_admin_fn,
    ):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery, winners, error = await _load_manual_menu(
            session,
            chat_id=chat.id,
            user_id=user.id,
            target_chat_id=target_chat_id,
            lottery_id=lottery_id,
            get_user_state_fn=get_user_state_fn,
            get_lottery_fn=get_lottery_fn,
        )
        if error:
            await handler.message_helper.safe_edit(update, error)
            await session.commit()
            return
        await session.commit()
    await _render_manual_draw_menu(
        update,
        handler,
        lottery,
        target_chat_id=target_chat_id,
        lottery_id=lottery_id,
        winners=winners,
    )
