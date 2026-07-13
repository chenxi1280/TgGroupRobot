from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.services.publish_service import PublishService
_HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_3 = 3
_HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_4 = 4


log = structlog.get_logger(__name__)


async def show_mall_catalog_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    products=None,
    setting=None,
    list_on_sale_products_func,
    get_or_create_mall_setting_func,
    keyboard_builder,
) -> None:
    if products is None or setting is None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            if products is None:
                products = await list_on_sale_products_func(session, chat_id)
            if setting is None:
                setting = await get_or_create_mall_setting_func(session, chat_id)
            await session.commit()

    text = "🏦 积分商城\n\n"
    if products:
        text += "\n".join(f"{p.name}｜{p.price_points}积分｜库存 {p.stock_left}" for p in products)
    else:
        text += "暂无可兑换商品。"

    if update.callback_query:
        message = update.callback_query.message
        if message and (message.photo or message.video):
            try:
                await update.callback_query.edit_message_caption(
                    caption=text,
                    reply_markup=keyboard_builder(chat_id, products),
                )
                return
            except Exception as exc:
                log.warning("mall_catalog_edit_caption_failed", chat_id=chat_id, error=str(exc))
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard_builder(chat_id, products),
        )
        return

    if update.effective_message:
        if setting and setting.cover_file_id:
            if setting.cover_media_type == "photo":
                await update.effective_message.reply_photo(
                    photo=setting.cover_file_id,
                    caption=text,
                    reply_markup=keyboard_builder(chat_id, products),
                )
                return
            if setting.cover_media_type == "video":
                await update.effective_message.reply_video(
                    video=setting.cover_file_id,
                    caption=text,
                    reply_markup=keyboard_builder(chat_id, products),
                )
                return
        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard_builder(chat_id, products),
        )


async def handle_mall_callback_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    ensure_user_func,
    redeem_product_func,
    get_or_create_mall_setting_func,
    list_on_sale_products_func,
    show_mall_catalog_func,
) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    data = update.callback_query.data or ""
    parts = data.split(":")
    if len(parts) < _HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_3:
        await answer_callback_query_safely(update, "无效操作", show_alert=True)
        return
    try:
        chat_id = int(parts[2])
    except ValueError:
        await answer_callback_query_safely(update, "无效群组", show_alert=True)
        return

    action = parts[1]
    db: Database = context.application.bot_data["db"]

    if action == "list":
        mark_callback_query_answered(update)
        await show_mall_catalog_func(update, context, chat_id)
        return

    if action == "redeem":
        if len(parts) < _HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_4:
            await answer_callback_query_safely(update, "无效商品", show_alert=True)
            return
        try:
            product_id = int(parts[3])
        except ValueError:
            await answer_callback_query_safely(update, "无效商品", show_alert=True)
            return

        async with db.session_factory() as session:
            await ensure_chat_func(session, chat_id=chat_id, chat_type="supergroup", title=None)
            await ensure_user_func(
                session,
                user_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
                language_code=update.effective_user.language_code,
            )
            success, reason, _order = await redeem_product_func(
                session,
                chat_id=chat_id,
                product_id=product_id,
                buyer_user_id=update.effective_user.id,
            )
            setting = await get_or_create_mall_setting_func(session, chat_id)
            await session.commit()

        if not success:
            await answer_callback_query_safely(update, reason, show_alert=True)
            return

        mark_callback_query_answered(update)
        await PublishService.send_temporary(
            context,
            chat_id=chat_id,
            text=f"兑换成功，订单已创建。用户：{update.effective_user.id}",
            delete_after_seconds=setting.redeem_notice_delete_seconds,
        )
        await show_mall_catalog_func(update, context, chat_id)
        return

    await answer_callback_query_safely(update, "暂不支持该操作", show_alert=True)
