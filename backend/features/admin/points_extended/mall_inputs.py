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

NUMERIC_PRODUCT_INPUTS = {
    "points_mall_product_price_input": (
        r"\d+",
        "所需积分必须是非负整数。",
        "price_points",
    ),
    "points_mall_product_limit_input": (
        r"\d+",
        "限购次数必须是非负整数。",
        "limit_per_user",
    ),
    "points_mall_product_stock_input": (
        r"\d+",
        "可售数量必须是非负整数。",
        "stock_total",
    ),
    "points_mall_product_sort_input": (r"-?\d+", "排序权重必须是整数。", "sort_weight"),
}


async def _finish_mall_input(
    update,
    context,
    session,
    *,
    target_chat_id: int,
    user_id: int,
    show_page,
    **page_kwargs,
) -> None:
    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await show_page(update, context, target_chat_id, **page_kwargs)


async def _handle_mall_command_input(
    update,
    context,
    session,
    *,
    module,
    text_value: str,
    target_chat_id: int,
    user_id: int,
) -> None:
    if not text_value:
        await update.effective_message.reply_text("商城指令不能为空。")
        return
    setting = await module.PointsExtendedService.get_or_create_mall_setting(
        session, target_chat_id
    )
    await module.PointsExtendedService.update_mall_setting(
        session, setting, entry_command=text_value[:32]
    )
    await _finish_mall_input(
        update,
        context,
        session,
        target_chat_id=target_chat_id,
        user_id=user_id,
        show_page=admin_handler_instance()._show_points_mall_menu,
    )


async def _cover_values(message, text_value: str):
    if text_value == "清空":
        return None, None
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    await message.reply_text("请发送图片或视频，或输入 清空。")
    return None


async def _handle_mall_cover_input(
    update,
    context,
    session,
    *,
    module,
    text_value: str,
    target_chat_id: int,
    user_id: int,
) -> None:
    values = await _cover_values(update.effective_message, text_value)
    if values is None:
        return
    setting = await module.PointsExtendedService.get_or_create_mall_setting(
        session, target_chat_id
    )
    await module.PointsExtendedService.update_mall_setting(
        session, setting, cover_media_type=values[0], cover_file_id=values[1]
    )
    await _finish_mall_input(
        update,
        context,
        session,
        target_chat_id=target_chat_id,
        user_id=user_id,
        show_page=admin_handler_instance()._show_points_mall_cover_page,
    )


async def _load_mall_product(
    update, session, state, *, module, target_chat_id: int, user_id: int
):
    product_id = parse_state_int(state, "product_id")
    if product_id is None:
        text = "商城商品状态异常，已自动退出，请重新进入页面。"
    else:
        product = await module.PointsExtendedService.get_product(
            session, target_chat_id, product_id
        )
        if product is not None:
            return product
        text = "商城商品不存在，请重新进入页面。"
    await clear_points_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await update.effective_message.reply_text(text)
    return None


async def _apply_numeric_product_input(
    message,
    session,
    product,
    *,
    service,
    state_type: str,
    text_value: str,
) -> tuple[bool, bool]:
    config = NUMERIC_PRODUCT_INPUTS.get(state_type)
    if config is None:
        return False, False
    if not re.fullmatch(config[0], text_value):
        await message.reply_text(config[1])
        return True, False
    value = int(text_value)
    if state_type == "points_mall_product_price_input" and value <= 0:
        await message.reply_text("所需积分必须大于 0。")
        return True, False
    if config[2] == "stock_total":
        await service.update_product_stock_total(session, product, stock_total=value)
    else:
        await service.update_product(
            session,
            product,
            **{
                config[2]: None
                if config[2] == "limit_per_user" and value == 0
                else value
            },
        )
    return True, True


async def _apply_product_description(
    session, product, *, service, text_value: str, message_text: str
) -> bool:
    description = None if text_value == "清空" else message_text.strip()
    await service.update_product(session, product, description=description)
    return True


async def _apply_product_cover(
    message, session, product, *, service, text_value: str
) -> bool:
    values = await _cover_values(message, text_value)
    if values is None:
        return False
    await service.update_product(
        session, product, cover_media_type=values[0], cover_file_id=values[1]
    )
    return True


async def _apply_product_fulfiller(
    message, session, product, *, service, text_value: str, target_chat_id: int
) -> bool:
    if text_value == "清空":
        await service.update_product(session, product, fulfiller_user_id=None)
        return True
    user_id = await service.resolve_user_id(session, text_value)
    if user_id is None:
        await message.reply_text("未找到该用户，请输入用户ID或已记录的用户名。")
        return False
    if not await service.is_chat_member(session, target_chat_id, user_id):
        await message.reply_text("发放人员必须是当前群组成员。")
        return False
    await service.update_product(session, product, fulfiller_user_id=user_id)
    return True


async def _apply_product_input(
    update,
    session,
    product,
    *,
    service,
    state_type: str,
    text_value: str,
    message_text: str,
    target_chat_id: int,
) -> bool:
    message = update.effective_message
    numeric_handled, numeric_applied = await _apply_numeric_product_input(
        message,
        session,
        product,
        service=service,
        state_type=state_type,
        text_value=text_value,
    )
    if numeric_handled:
        return numeric_applied
    if state_type == "points_mall_product_name_input":
        if not text_value:
            await message.reply_text("商品名称不能为空。")
            return False
        await service.update_product(session, product, name=text_value[:128])
        return True
    if state_type == "points_mall_fulfiller_input":
        return await _apply_product_fulfiller(
            message,
            session,
            product,
            service=service,
            text_value=text_value,
            target_chat_id=target_chat_id,
        )
    if state_type == "points_mall_desc_input":
        return await _apply_product_description(
            session,
            product,
            service=service,
            text_value=text_value,
            message_text=message_text,
        )
    if state_type == "points_mall_product_cover_input":
        return await _apply_product_cover(
            message, session, product, service=service, text_value=text_value
        )
    return False


async def _handle_mall_product_input(
    update,
    context,
    session,
    *,
    module,
    state,
    message_text: str,
    target_chat_id: int,
    user_id: int,
) -> None:
    product = await _load_mall_product(
        update,
        session,
        state,
        module=module,
        target_chat_id=target_chat_id,
        user_id=user_id,
    )
    if product is None:
        return
    applied = await _apply_product_input(
        update,
        session,
        product,
        service=module.PointsExtendedService,
        state_type=state.state_type,
        text_value=message_text.strip(),
        message_text=message_text,
        target_chat_id=target_chat_id,
    )
    if not applied:
        return
    await _finish_mall_input(
        update,
        context,
        session,
        target_chat_id=target_chat_id,
        user_id=user_id,
        show_page=admin_handler_instance()._show_points_mall_product_detail,
        product_id=product.product_id,
    )


async def handle_points_mall_input(
    update,
    context,
    session,
    *,
    state,
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
        await _handle_mall_command_input(
            update,
            context,
            session,
            module=module,
            text_value=text_value,
            target_chat_id=target_chat_id,
            user_id=user_id,
        )
        return True

    if state_type == "points_mall_cover_input":
        await _handle_mall_cover_input(
            update,
            context,
            session,
            module=module,
            text_value=text_value,
            target_chat_id=target_chat_id,
            user_id=user_id,
        )
        return True

    if state_type not in PRODUCT_INPUT_STATES:
        return False

    await _handle_mall_product_input(
        update,
        context,
        session,
        module=module,
        state=state,
        message_text=message_text,
        target_chat_id=target_chat_id,
        user_id=user_id,
    )
    return True
