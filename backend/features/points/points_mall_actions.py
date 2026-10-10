from __future__ import annotations
from backend.features.points.services.mall_labels import ORDER_STATUS_NAMES

import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.features.points.services.points_service import get_balance
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.services.publish_service import PublishService
_HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_3 = 3
_HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_4 = 4


log = structlog.get_logger(__name__)


def _mall_catalog_text(products) -> str:
    if not products:
        return "🏦 积分商城\n\n暂无可兑换商品。"
    items = "\n".join(f"{product.name[:32]}｜{product.price_points}积分｜库存 {product.stock_left}" for product in products)
    return f"🏦 积分商城\n\n{items}"


async def _edit_mall_catalog(update, text: str, products, *, chat_id: int, keyboard_builder) -> bool:
    if update.callback_query is None:
        return False
    markup = keyboard_builder(chat_id, products)
    message = update.callback_query.message
    if message and (message.photo or message.video):
        try:
            await update.callback_query.edit_message_caption(caption=text, reply_markup=markup)
            return True
        except Exception as exc:
            log.warning("mall_catalog_edit_caption_failed", chat_id=chat_id, error=str(exc))
    await update.callback_query.edit_message_text(text, reply_markup=markup)
    return True


async def _send_mall_catalog(update, text: str, products, *, chat_id: int, setting, keyboard_builder) -> None:
    if update.effective_message is None:
        return
    markup = keyboard_builder(chat_id, products)
    if setting and setting.cover_file_id and setting.cover_media_type == "photo":
        await update.effective_message.reply_photo(photo=setting.cover_file_id, caption=text, reply_markup=markup)
        return
    if setting and setting.cover_file_id and setting.cover_media_type == "video":
        await update.effective_message.reply_video(video=setting.cover_file_id, caption=text, reply_markup=markup)
        return
    await update.effective_message.reply_text(text, reply_markup=markup)


async def _mall_callback_scope(update):
    parts = (update.callback_query.data or "").split(":")
    if len(parts) < _HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_3:
        await answer_callback_query_safely(update, "无效操作", show_alert=True)
        return None
    try:
        chat_id = int(parts[2])
    except ValueError:
        await answer_callback_query_safely(update, "无效群组", show_alert=True)
        return None
    return parts[1], chat_id, parts


def _mall_product_id(parts: list[str]) -> int | None:
    if len(parts) < _HANDLE_MALL_CALLBACK_ACTION_THRESHOLD_4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


async def _show_mall_page(update, text, rows, *, photo=None, media_type=None):
    from backend.features.points.mall_presentation import send_mall_page
    await send_mall_page(update, text, rows, media=photo, media_type=media_type)


MALL_ACTION_PARTS = 4


async def _mall_trade_page(update, context, db, *, action, chat_id, parts,
                          ensure_chat_func, ensure_user_func):
    user = update.effective_user
    back = [InlineKeyboardButton("返回商城", callback_data=f"mall:list:{chat_id}")]
    # Group membership is rechecked at confirmation, including forwarded buttons.
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
    except TelegramError:
        await answer_callback_query_safely(update, "暂时无法核验群成员身份，请稍后重试", show_alert=True)
        return
    if member.status in {"left", "kicked"} or (member.status == "restricted" and not member.is_member):
        await answer_callback_query_safely(update, "请先加入商品所属群", show_alert=True)
        return
    async with db.session_factory() as session:
        await ensure_chat_func(session, chat_id=chat_id, chat_type="supergroup", title=None)
        await ensure_user_func(session, user_id=user.id, username=user.username,
                               first_name=user.first_name, last_name=user.last_name,
                               language_code=user.language_code)
        if action in {"cancel", "confirm"}:
            await _resolve_trade_intent(update, session, action=action, parts=parts, chat_id=chat_id, user=user, back=back)
            return
        product_id = _mall_product_id(parts)
        product = await PointsExtendedService.get_product(session, chat_id, product_id) if product_id else None
        if product is None:
            await _show_mall_page(update, "商品不存在，请刷新商城", [back])
            return
        if action == "prepare":
            intent, error = await PointsExtendedService.create_redeem_intent(
                session, chat_id=chat_id, product_id=product_id, buyer_user_id=user.id)
            if error:
                await _show_mall_page(update, error, [back])
                return
            balance = await get_balance(session, chat_id=chat_id, user_id=user.id)
            await session.commit()
            await _show_mall_page(update,
                f"确认兑换：{product.name}\n数量：1\n本次扣分：{product.price_points}\n"
                f"当前积分：{balance}\n预计剩余：{balance-product.price_points}\n"
                "确认有效期 10 分钟，提交时重新核验余额和库存。",
                [[InlineKeyboardButton("确认本次兑换", callback_data=f"mall:confirm:{chat_id}:{intent.token}")],
                 [InlineKeyboardButton("取消本次确认", callback_data=f"mall:cancel:{chat_id}:{intent.token}")]])
            return
        from backend.features.points.mall_presentation import product_detail_text
        text = product_detail_text(product)
        rows = [[InlineKeyboardButton("兑换", callback_data=f"mall:prepare:{chat_id}:{product_id}")], back]
        await session.commit()
        await _show_mall_page(update, text, rows,
                              photo=product.cover_file_id, media_type=product.cover_media_type)


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

    if not setting.enabled:
        products = []
    requested_page = _catalog_page(update)
    total = len(products)
    page = max(0, min(requested_page, max(0, (total-1)//8)))
    products = products[page*8:(page+1)*8]
    base_keyboard_builder = keyboard_builder
    def paged_keyboard(target, visible):
        rows = [list(row) for row in base_keyboard_builder(target, visible).inline_keyboard]
        nav = []
        if page:
            nav.append(InlineKeyboardButton("上一页", callback_data=f"mall:list:{chat_id}:{page-1}"))
        if (page+1)*8 < total:
            nav.append(InlineKeyboardButton("下一页", callback_data=f"mall:list:{chat_id}:{page+1}"))
        if nav:
            rows.append(nav)
        return InlineKeyboardMarkup(rows)
    keyboard_builder = paged_keyboard
    text = (_mall_catalog_text(products) + f"\n共 {total} 件商品 · 第 {page+1}/{max(1,(total+7)//8)} 页") if setting.enabled else "商城已关闭，已有订单仍有效。"
    if await _edit_mall_catalog(update, text, products, chat_id=chat_id, keyboard_builder=keyboard_builder):
        return
    await _send_mall_catalog(
        update,
        text,
        products,
        chat_id=chat_id,
        setting=setting,
        keyboard_builder=keyboard_builder,
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

    scope = await _mall_callback_scope(update)
    if scope is None:
        return
    action, chat_id, parts = scope
    db: Database = context.application.bot_data["db"]
    if action == "list":
        mark_callback_query_answered(update)
        await show_mall_catalog_func(update, context, chat_id)
        return

    if action in {"redeem", "detail", "prepare", "confirm", "cancel"}:
        await _mall_trade_page(update, context, db, action=action, chat_id=chat_id,
                              parts=parts, ensure_chat_func=ensure_chat_func,
                              ensure_user_func=ensure_user_func)
        return

    await answer_callback_query_safely(update, "暂不支持该操作", show_alert=True)


async def _resolve_trade_intent(update, session, *, action, parts, chat_id, user, back):
    if action == "cancel":
        reason, product_id = await PointsExtendedService.cancel_redeem_intent(session,
            chat_id=chat_id, token=parts[3] if len(parts) == MALL_ACTION_PARTS else "", buyer_user_id=user.id)
        await session.commit()
        rows = [[InlineKeyboardButton("返回商品", callback_data=f"mall:detail:{chat_id}:{product_id}")], back] if product_id else [back]
        await _show_mall_page(update, reason, rows)
        return
    if action == "confirm":
        token = parts[3] if len(parts) == MALL_ACTION_PARTS else ""
        success, reason, order = await PointsExtendedService.confirm_redeem_intent(
            session, chat_id=chat_id, token=token, buyer_user_id=user.id)
        await session.commit()
        if not success:
            await _show_mall_page(update, reason, [back])
            return
        await _show_mall_page(update,
            f"{reason}\n订单 #{order.order_id}\n扣分：{order.price_points}\n"
            f"状态：{ORDER_STATUS_NAMES.get(order.order_status, order.order_status)}\n发放方式：人工发放",
            [[InlineKeyboardButton("查看订单", callback_data=f"morder:detail:{chat_id}:{order.order_id}")], back])
        return


def _catalog_page(update):
    parts = (update.callback_query.data or "").split(":") if update.callback_query else []
    return int(parts[3]) if len(parts) == MALL_ACTION_PARTS and parts[1] == "list" and parts[3].isdigit() else 0
