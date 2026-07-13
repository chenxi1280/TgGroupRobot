from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def ads_detail_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    parse_ad_id_func,
    get_ad_func,
    format_ad_detail_text_func,
    ads_menu_keyboard_func,
    ads_detail_keyboard_func,
    answer_callback_query_safely_func,
    mark_callback_query_answered_func,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    mark_callback_query_answered_func(update)

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    ad_id = parse_ad_id_func(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely_func(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad_func(session, ad_id)
        if not ad:
            await session.commit()
            await q.edit_message_text("轮播广告不存在", reply_markup=ads_menu_keyboard_func(target_chat_id))
            return
        if ad.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely_func(update, "该广告不属于当前群组")
            return

        text = format_ad_detail_text_func(ad)
        await session.commit()

    await q.edit_message_text(text, reply_markup=ads_detail_keyboard_func(ad_id, ad.enabled))


async def _load_ad_for_send(
    update, *, db, q, ad_id: int, target_chat_id: int,
    get_ad_func, answer_callback_query_safely_func,
):
    async with db.session_factory() as session:
        ad = await get_ad_func(session, ad_id)
        await session.commit()
    if ad is None:
        await q.edit_message_text("广告不存在")
        return None
    if ad.chat_id != target_chat_id:
        await answer_callback_query_safely_func(update, "该广告不属于当前群组")
        return None
    return ad


async def _publish_ad_now(context, *, ad, format_ad_push_text_func, publish_service) -> None:
    text = format_ad_push_text_func(ad)
    if ad.image_file_id:
        await publish_service.send_photo(
            context, chat_id=ad.chat_id, photo=ad.image_file_id, caption=text
        )
        return
    await publish_service.send(context, chat_id=ad.chat_id, text=text)


async def _mark_and_render_sent_ad(
    *, db, q, ad_id: int, mark_ad_sent_func, get_ad_func,
    format_ad_detail_text_func, ads_detail_keyboard_func,
) -> None:
    async with db.session_factory() as session:
        await mark_ad_sent_func(session, ad_id)
        await session.commit()
        updated = await get_ad_func(session, ad_id)
        await session.commit()
    text = format_ad_detail_text_func(updated)
    await q.edit_message_text(
        text, reply_markup=ads_detail_keyboard_func(ad_id, updated.enabled)
    )


async def _send_loaded_ad(
    context, *, ad, db, q, ad_id: int, format_ad_push_text_func,
    publish_service, mark_ad_sent_func, get_ad_func,
    format_ad_detail_text_func, ads_detail_keyboard_func,
    build_public_error_text_func,
) -> None:
    try:
        await _publish_ad_now(
            context, ad=ad, format_ad_push_text_func=format_ad_push_text_func,
            publish_service=publish_service,
        )
        await _mark_and_render_sent_ad(
            db=db, q=q, ad_id=ad_id, mark_ad_sent_func=mark_ad_sent_func,
            get_ad_func=get_ad_func,
            format_ad_detail_text_func=format_ad_detail_text_func,
            ads_detail_keyboard_func=ads_detail_keyboard_func,
        )
    except Exception as exc:
        await q.edit_message_text(
            f"❌ 发送失败: {build_public_error_text_func(exc, fallback='请稍后重试')}"
        )


async def ads_send_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    parse_ad_id_func,
    get_ad_func,
    format_ad_push_text_func,
    format_ad_detail_text_func,
    mark_ad_sent_func,
    ads_detail_keyboard_func,
    answer_callback_query_safely_func,
    mark_callback_query_answered_func,
    build_public_error_text_func,
    publish_service,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    mark_callback_query_answered_func(update)

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    ad_id = parse_ad_id_func(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely_func(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    ad = await _load_ad_for_send(
        update, db=db, q=q, ad_id=ad_id, target_chat_id=target_chat_id,
        get_ad_func=get_ad_func,
        answer_callback_query_safely_func=answer_callback_query_safely_func,
    )
    if ad is None:
        return
    await _send_loaded_ad(
        context, ad=ad, db=db, q=q, ad_id=ad_id,
        format_ad_push_text_func=format_ad_push_text_func,
        publish_service=publish_service, mark_ad_sent_func=mark_ad_sent_func,
        get_ad_func=get_ad_func,
        format_ad_detail_text_func=format_ad_detail_text_func,
        ads_detail_keyboard_func=ads_detail_keyboard_func,
        build_public_error_text_func=build_public_error_text_func,
    )


async def ads_toggle_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    parse_ad_id_func,
    get_ad_func,
    toggle_ad_func,
    format_ad_detail_text_func,
    ads_detail_keyboard_func,
    answer_callback_query_safely_func,
    mark_callback_query_answered_func,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    mark_callback_query_answered_func(update)

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    ad_id = parse_ad_id_func(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely_func(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad_func(session, ad_id)
        if ad is None:
            await q.edit_message_text("广告不存在")
            return
        if ad.chat_id != target_chat_id:
            await answer_callback_query_safely_func(update, "该广告不属于当前群组")
            await session.commit()
            return

        ad = await toggle_ad_func(session, ad_id)
        await session.commit()

    text = format_ad_detail_text_func(ad)
    await q.edit_message_text(text, reply_markup=ads_detail_keyboard_func(ad_id, ad.enabled))


async def ads_delete_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    parse_ad_id_func,
    get_ad_func,
    delete_ad_func,
    ads_menu_keyboard_func,
    answer_callback_query_safely_func,
    mark_callback_query_answered_func,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    mark_callback_query_answered_func(update)

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    ad_id = parse_ad_id_func(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely_func(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad_func(session, ad_id)
        if ad is None:
            await q.edit_message_text("广告不存在")
            return
        if ad.chat_id != target_chat_id:
            await answer_callback_query_safely_func(update, "该广告不属于当前群组")
            await session.commit()
            return

        await delete_ad_func(session, ad_id)
        await session.commit()

    await q.edit_message_text(
        "✅ 广告已删除",
        reply_markup=ads_menu_keyboard_func(target_chat_id),
    )
