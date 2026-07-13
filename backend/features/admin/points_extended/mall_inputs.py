from __future__ import annotations

import re

from backend.features.admin.points_extended.runtime import (
    admin_handler_instance,
    admin_module,
    clear_points_state,
    parse_state_int,
)


PRODUCT_INPUT_STATES = {
    "points_mall_product_name_input",
    "points_mall_product_price_input",
    "points_mall_product_limit_input",
    "points_mall_product_stock_input",
    "points_mall_fulfiller_input",
    "points_mall_desc_input",
    "points_mall_product_sort_input",
    "points_mall_product_cover_input",
}


async def handle_points_mall_input(
    update,
    context,
    session,
    *, state,
    message_text: str,

    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    module = admin_module()
    user_id = update.effective_user.id
    text_value = message_text.strip()
    state_type = state.state_type

    if state_type == "points_mall_command_input":
        if not text_value:
            await update.effective_message.reply_text("商城指令不能为空。")
            return True
        setting = await module.PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        await module.PointsExtendedService.update_mall_setting(session, setting, entry_command=text_value[:32])
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await admin_handler_instance()._show_points_mall_menu(update, context, target_chat_id)
        return True

    if state_type == "points_mall_cover_input":
        setting = await module.PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        if text_value == "清空":
            await module.PointsExtendedService.update_mall_setting(
                session,
                setting,
                cover_media_type=None,
                cover_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await module.PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="photo",
                    cover_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await module.PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="video",
                    cover_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                return True
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await admin_handler_instance()._show_points_mall_cover_page(update, context, target_chat_id)
        return True

    if state_type not in PRODUCT_INPUT_STATES:
        return False

    product_id = parse_state_int(state, "product_id")
    if product_id is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("商城商品状态异常，已自动退出，请重新进入页面。")
        return True

    product = await module.PointsExtendedService.get_product(session, target_chat_id, product_id)
    if product is None:
        await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("商城商品不存在，请重新进入页面。")
        return True

    if state_type == "points_mall_product_name_input":
        if not text_value:
            await update.effective_message.reply_text("商品名称不能为空。")
            return True
        await module.PointsExtendedService.update_product(session, product, name=text_value[:128])
    elif state_type == "points_mall_product_price_input":
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("所需积分必须是非负整数。")
            return True
        price_value = int(text_value)
        if price_value <= 0:
            await update.effective_message.reply_text("所需积分必须大于 0。")
            return True
        await module.PointsExtendedService.update_product(session, product, price_points=price_value)
    elif state_type == "points_mall_product_limit_input":
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("限购次数必须是非负整数。")
            return True
        limit_value = int(text_value)
        await module.PointsExtendedService.update_product(
            session,
            product,
            limit_per_user=(None if limit_value == 0 else limit_value),
        )
    elif state_type == "points_mall_product_stock_input":
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("可售数量必须是非负整数。")
            return True
        await module.PointsExtendedService.update_product_stock_total(
            session,
            product,
            stock_total=int(text_value),
        )
    elif state_type == "points_mall_fulfiller_input":
        if text_value == "清空":
            await module.PointsExtendedService.update_product(session, product, fulfiller_user_id=None)
        else:
            fulfiller_user_id = await module.PointsExtendedService.resolve_user_id(session, text_value)
            if fulfiller_user_id is None:
                await update.effective_message.reply_text("未找到该用户，请输入用户ID或已记录的用户名。")
                return True
            if not await module.PointsExtendedService.is_chat_member(session, target_chat_id, fulfiller_user_id):
                await update.effective_message.reply_text("发放人员必须是当前群组成员。")
                return True
            await module.PointsExtendedService.update_product(session, product, fulfiller_user_id=fulfiller_user_id)
    elif state_type == "points_mall_desc_input":
        await module.PointsExtendedService.update_product(
            session,
            product,
            description=None if text_value == "清空" else message_text.strip(),
        )
    elif state_type == "points_mall_product_sort_input":
        if not re.fullmatch(r"-?\d+", text_value):
            await update.effective_message.reply_text("排序权重必须是整数。")
            return True
        await module.PointsExtendedService.update_product(session, product, sort_weight=int(text_value))
    elif state_type == "points_mall_product_cover_input":
        if text_value == "清空":
            await module.PointsExtendedService.update_product(
                session,
                product,
                cover_media_type=None,
                cover_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await module.PointsExtendedService.update_product(
                    session,
                    product,
                    cover_media_type="photo",
                    cover_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await module.PointsExtendedService.update_product(
                    session,
                    product,
                    cover_media_type="video",
                    cover_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                return True
    else:
        return False

    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_points_mall_product_detail(update, context, target_chat_id, product_id=product.product_id)
    return True
