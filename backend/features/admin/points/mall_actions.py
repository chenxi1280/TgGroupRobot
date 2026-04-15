from __future__ import annotations

from backend.features.admin.support import *


class PointsMallActionsMixin:
    async def _handle_points_mall(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击可配置项继续编辑")
            return
        db: Database = context.application.bot_data["db"]
        if op == "toggle":
            field = callback_data.get(4)
            value = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                if field == "enabled":
                    await PointsExtendedService.update_mall_setting(session, setting, enabled=value)
                elif field == "auto_unlist":
                    await PointsExtendedService.update_mall_setting(session, setting, auto_unlist_when_out_of_stock=value)
                await session.commit()
            await self._show_points_mall_menu(update, context, chat_id)
            return
        if op == "edit" and callback_data.get(4) == "command":
            await self._show_points_mall_command_page(update, context, chat_id)
            return
        if op == "edit" and callback_data.get(4) == "notice":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await session.commit()
            await self.message_helper.safe_edit(
                update,
                text="🧾 积分商城 | 兑换通知\n\n请选择兑换提示消息的删除方式：",
                reply_markup=points_mall_notice_keyboard(chat_id, setting.redeem_notice_delete_seconds),
            )
            return
        if op == "edit" and callback_data.get(4) == "cover":
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type="points_mall_cover_input",
                    state_data={"target_chat_id": chat_id},
                )
                await session.commit()
            await self.message_helper.safe_edit(
                update,
                text="🛍️ 积分商城 | 商城封面\n\n👉 请发送图片或视频文件，或输入 清空",
                reply_markup=points_mall_cover_keyboard(chat_id),
            )
            return
        if op == "notice":
            seconds = callback_data.get_int(4)
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    redeem_notice_delete_seconds=seconds,
                )
                await session.commit()
            await self._show_points_mall_menu(update, context, chat_id)
            return
        if op == "cover" and callback_data.get(4) == "clear":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type=None,
                    cover_file_id=None,
                )
                await session.commit()
            await self._show_points_mall_cover_page(update, context, chat_id)
            return
        if op == "orders":
            product_id = callback_data.get_int_optional(4)
            status = _normalize_mall_order_status(callback_data.get(5) or "a")
            await self._show_points_mall_orders_page(update, context, chat_id, product_id=product_id, status=status)
            return
        if op == "orders_status":
            status = _normalize_mall_order_status(callback_data.get(4) or "a")
            product_id = callback_data.get_int_optional(5)
            await self._show_points_mall_orders_page(update, context, chat_id, product_id=product_id, status=status)
            return
        if op == "order":
            sub = callback_data.get(4)
            order_id = callback_data.get_int(5)
            status = _normalize_mall_order_status(callback_data.get(6) or "a")
            product_token = callback_data.get_int_optional(7)
            product_id = None if product_token in {None, 0} else product_token
            if sub == "detail":
                await self._show_points_mall_order_detail(update, context, chat_id, order_id, status=status, product_id=product_id)
                return
            async with db.session_factory() as session:
                if sub == "fulfill":
                    success, message, _order = await PointsExtendedService.fulfill_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                elif sub == "cancel":
                    success, message, _order = await PointsExtendedService.cancel_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                elif sub == "refund":
                    success, message, _order = await PointsExtendedService.refund_order(
                        session,
                        chat_id=chat_id,
                        order_id=order_id,
                        operator_user_id=update.effective_user.id,
                    )
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "未识别的订单操作，请刷新页面后重试", show_alert=True)
                    return
                await session.commit()
            await answer_callback_query_safely(update, message, show_alert=not success)
            await self._show_points_mall_order_detail(update, context, chat_id, order_id, status=status, product_id=product_id)
            return
        if op == "product":
            sub = callback_data.get(4)
            if sub == "add":
                async with db.session_factory() as session:
                    product = await PointsExtendedService.create_product(session, chat_id)
                    await session.commit()
                await self._show_points_mall_product_detail(update, context, chat_id, product.product_id)
                return
            if sub == "detail":
                await self._show_points_mall_product_detail(update, context, chat_id, callback_data.get_int(5))
                return
            if sub == "preview":
                await self._show_points_mall_product_preview(update, context, chat_id, callback_data.get_int(5))
                return
            if sub == "toggle":
                product_id = callback_data.get_int(5)
                enabled = bool(callback_data.get_int(6))
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    if product is not None:
                        await PointsExtendedService.update_product_status(session, product, on_sale=enabled)
                    await session.commit()
                await self._show_points_mall_product_detail(update, context, chat_id, product_id)
                return
            if sub == "delete":
                product_id = callback_data.get_int(5)
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    if product is not None:
                        await PointsExtendedService.delete_product(session, product)
                    await session.commit()
                await self._show_points_mall_products_page(update, context, chat_id)
                return
            if sub == "delete_confirm":
                product_id = callback_data.get_int(5)
                async with db.session_factory() as session:
                    product = await PointsExtendedService.get_product(session, chat_id, product_id)
                    await session.commit()
                if product is None:
                    await answer_callback_query_safely(update, "商品不存在", show_alert=True)
                    await self._show_points_mall_products_page(update, context, chat_id)
                    return
                await self.message_helper.safe_edit(
                    update,
                    text="\n".join(
                        [
                            "🛍️ 管理商品 | 删除商品",
                            "",
                            f"商品名称：{product.name}",
                            f"兑换价格：{product.price_points}",
                            "",
                            "确认后将删除该商品。",
                        ]
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("确认删除", callback_data=f"adm:mall:{chat_id}:product:delete:{product_id}")],
                            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")],
                        ]
                    ),
                )
                return
            if sub == "edit":
                product_id = callback_data.get_int(5)
                field = callback_data.get(6)
                if field == "cover":
                    async with db.session_factory() as session:
                        await set_user_state(
                            session,
                            chat_id=update.effective_user.id,
                            user_id=update.effective_user.id,
                            state_type="points_mall_product_cover_input",
                            state_data={"target_chat_id": chat_id, "product_id": product_id},
                        )
                        await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        text="🛍️ 管理商品 | 上传封面\n\n👉 请发送图片或视频文件，或输入 清空",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
                        ),
                    )
                    return
                state_map = {
                    "name": ("points_mall_product_name_input", "👉 请输入商品名称："),
                    "price": ("points_mall_product_price_input", "👉 请输入所需积分："),
                    "limit": ("points_mall_product_limit_input", "👉 请输入限购次数（输入 0 表示不限购）："),
                    "stock": ("points_mall_product_stock_input", "👉 请输入可售总数量："),
                    "fulfiller": ("points_mall_fulfiller_input", "👉 请输入发放人员用户名或用户ID（输入 清空 取消设置）："),
                    "description": ("points_mall_desc_input", "👉 请输入兑换说明（输入 清空 清空说明）："),
                    "sort": ("points_mall_product_sort_input", "👉 请输入排序权重："),
                }
                state_entry = state_map.get(field)
                if state_entry is None:
                    await answer_callback_query_safely(update, "未识别的商品字段，请刷新页面后重试", show_alert=True)
                    return
                state_type, prompt = state_entry
                async with db.session_factory() as session:
                    await set_user_state(
                        session,
                        chat_id=update.effective_user.id,
                        user_id=update.effective_user.id,
                        state_type=state_type,
                        state_data={"target_chat_id": chat_id, "product_id": product_id},
                    )
                    await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    text=prompt,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
                    ),
                )
                return
        await answer_callback_query_safely(update, "未识别的积分商城操作，请刷新页面后重试", show_alert=True)
