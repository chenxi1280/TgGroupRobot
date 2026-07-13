from __future__ import annotations

from backend.features.admin.support import *


class PointsMallActionsMixin:
    async def _toggle_mall_setting(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        fields = {
            "enabled": "enabled",
            "auto_unlist": "auto_unlist_when_out_of_stock",
        }
        field = fields.get(callback_data.get(4))
        if field is None:
            await answer_callback_query_safely(update, "未识别的商城设置", show_alert=True)
            return
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await PointsExtendedService.update_mall_setting(
                session, setting, **{field: bool(callback_data.get_int(5))}
            )
            await session.commit()
        await self._show_points_mall_menu(update, context, chat_id)

    async def _start_mall_input(
        self, update, context, *, db, chat_id: int, state_type: str,
        state_data: dict, prompt: str, callback: str, reply_markup=None,
    ) -> None:
        async with db.session_factory() as session:
            await set_user_state(
                session, chat_id=update.effective_user.id,
                user_id=update.effective_user.id, state_type=state_type,
                state_data={"target_chat_id": chat_id, **state_data},
            )
            await session.commit()
        keyboard = reply_markup or InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=callback)]]
        )
        await self.message_helper.safe_edit(update, text=prompt, reply_markup=keyboard)

    async def _handle_mall_edit(
        self, update, context, *, db, chat_id: int, field: str
    ) -> bool:
        if field == "command":
            await self._show_points_mall_command_page(update, context, chat_id)
            return True
        if field == "notice":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await session.commit()
            await self.message_helper.safe_edit(
                update, text="🧾 积分商城 | 兑换通知\n\n请选择兑换提示消息的删除方式：",
                reply_markup=points_mall_notice_keyboard(
                    chat_id, setting.redeem_notice_delete_seconds
                ),
            )
            return True
        if field != "cover":
            return False
        await self._start_mall_input(
            update, context, db=db, chat_id=chat_id,
            state_type="points_mall_cover_input", state_data={},
            prompt="🛍️ 积分商城 | 商城封面\n\n👉 请发送图片或视频文件，或输入 清空",
            callback=f"adm:mall:{chat_id}:edit:cover",
            reply_markup=points_mall_cover_keyboard(chat_id),
        )
        return True

    async def _handle_mall_settings(
        self, update, context, *, db, chat_id: int, op: str, callback_data
    ) -> bool:
        if op == "toggle":
            await self._toggle_mall_setting(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return True
        if op == "edit":
            return await self._handle_mall_edit(
                update, context, db=db, chat_id=chat_id, field=callback_data.get(4)
            )
        if op == "notice":
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await PointsExtendedService.update_mall_setting(
                    session, setting,
                    redeem_notice_delete_seconds=callback_data.get_int(4),
                )
                await session.commit()
            await self._show_points_mall_menu(update, context, chat_id)
            return True
        if op != "cover" or callback_data.get(4) != "clear":
            return False
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await PointsExtendedService.update_mall_setting(
                session, setting, cover_media_type=None, cover_file_id=None
            )
            await session.commit()
        await self._show_points_mall_cover_page(update, context, chat_id)
        return True

    async def _handle_mall_order(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(4)
        order_id = callback_data.get_int(5)
        status = _normalize_mall_order_status(callback_data.get(6) or "a")
        product_token = callback_data.get_int_optional(7)
        product_id = None if product_token in {None, 0} else product_token
        if sub == "detail":
            await self._show_points_mall_order_detail(
                update, context, chat_id, order_id=order_id,
                status=status, product_id=product_id,
            )
            return
        actions = {
            "fulfill": PointsExtendedService.fulfill_order,
            "cancel": PointsExtendedService.cancel_order,
            "refund": PointsExtendedService.refund_order,
        }
        action = actions.get(sub)
        if action is None:
            await answer_callback_query_safely(
                update, "未识别的订单操作，请刷新页面后重试", show_alert=True
            )
            return
        async with db.session_factory() as session:
            success, message, _order = await action(
                session, chat_id=chat_id, order_id=order_id,
                operator_user_id=update.effective_user.id,
            )
            await session.commit()
        await answer_callback_query_safely(update, message, show_alert=not success)
        await self._show_points_mall_order_detail(
            update, context, chat_id, order_id=order_id,
            status=status, product_id=product_id,
        )

    async def _create_mall_product(
        self, update, context, *, db, chat_id: int
    ) -> None:
        async with db.session_factory() as session:
            product = await PointsExtendedService.create_product(session, chat_id)
            await session.commit()
        await self._show_points_mall_product_detail(
            update, context, chat_id, product_id=product.product_id
        )

    async def _toggle_mall_product(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        product_id = callback_data.get_int(5)
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            if product is not None:
                await PointsExtendedService.update_product_status(
                    session, product, on_sale=bool(callback_data.get_int(6))
                )
            await session.commit()
        await self._show_points_mall_product_detail(
            update, context, chat_id, product_id=product_id
        )

    async def _delete_mall_product(
        self, update, context, *, db, chat_id: int, product_id: int
    ) -> None:
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            if product is not None:
                await PointsExtendedService.delete_product(session, product)
            await session.commit()
        await self._show_points_mall_products_page(update, context, chat_id)

    async def _confirm_mall_product_delete(
        self, update, context, *, db, chat_id: int, product_id: int
    ) -> None:
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            await session.commit()
        if product is None:
            await answer_callback_query_safely(update, "商品不存在", show_alert=True)
            await self._show_points_mall_products_page(update, context, chat_id)
            return
        text = "\n".join([
            "🛍️ 管理商品 | 删除商品", "", f"商品名称：{product.name}",
            f"兑换价格：{product.price_points}", "", "确认后将删除该商品。",
        ])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "确认删除", callback_data=f"adm:mall:{chat_id}:product:delete:{product_id}"
            )],
            [InlineKeyboardButton(
                "🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}"
            )],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _edit_mall_product(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        product_id = callback_data.get_int(5)
        field = callback_data.get(6)
        callback = f"adm:mall:{chat_id}:product:detail:{product_id}"
        if field == "cover":
            await self._start_mall_input(
                update, context, db=db, chat_id=chat_id,
                state_type="points_mall_product_cover_input",
                state_data={"product_id": product_id},
                prompt="🛍️ 管理商品 | 上传封面\n\n👉 请发送图片或视频文件，或输入 清空",
                callback=callback,
            )
            return
        fields = {
            "name": ("points_mall_product_name_input", "👉 请输入商品名称："),
            "price": ("points_mall_product_price_input", "👉 请输入所需积分："),
            "limit": ("points_mall_product_limit_input", "👉 请输入限购次数（输入 0 表示不限购）："),
            "stock": ("points_mall_product_stock_input", "👉 请输入可售总数量："),
            "fulfiller": ("points_mall_fulfiller_input", "👉 请输入发放人员用户名或用户ID（输入 清空 取消设置）："),
            "description": ("points_mall_desc_input", "👉 请输入兑换说明（输入 清空 清空说明）："),
            "sort": ("points_mall_product_sort_input", "👉 请输入排序权重："),
        }
        config = fields.get(field)
        if config is None:
            await answer_callback_query_safely(
                update, "未识别的商品字段，请刷新页面后重试", show_alert=True
            )
            return
        await self._start_mall_input(
            update, context, db=db, chat_id=chat_id, state_type=config[0],
            state_data={"product_id": product_id}, prompt=config[1], callback=callback,
        )

    async def _handle_mall_product(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(4)
        if sub == "add":
            await self._create_mall_product(update, context, db=db, chat_id=chat_id)
            return
        product_id = callback_data.get_int(5)
        if sub == "detail":
            await self._show_points_mall_product_detail(
                update, context, chat_id, product_id=product_id
            )
            return
        if sub == "preview":
            await self._show_points_mall_product_preview(
                update, context, chat_id, product_id=product_id
            )
            return
        if sub == "toggle":
            await self._toggle_mall_product(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return
        if sub == "delete":
            await self._delete_mall_product(
                update, context, db=db, chat_id=chat_id, product_id=product_id
            )
            return
        if sub == "delete_confirm":
            await self._confirm_mall_product_delete(
                update, context, db=db, chat_id=chat_id, product_id=product_id
            )
            return
        if sub == "edit":
            await self._edit_mall_product(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return
        await answer_callback_query_safely(
            update, "未识别的商品操作，请刷新页面后重试", show_alert=True
        )

    async def _handle_points_mall(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击可配置项继续编辑")
            return
        db: Database = context.application.bot_data["db"]
        if await self._handle_mall_settings(
            update, context, db=db, chat_id=chat_id, op=op,
            callback_data=callback_data,
        ):
            return
        if op in {"orders", "orders_status"}:
            status_index, product_index = (5, 4) if op == "orders" else (4, 5)
            await self._show_points_mall_orders_page(
                update, context, chat_id,
                product_id=callback_data.get_int_optional(product_index),
                status=_normalize_mall_order_status(callback_data.get(status_index) or "a"),
            )
            return
        if op == "order":
            await self._handle_mall_order(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return
        if op == "product":
            await self._handle_mall_product(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return
        await answer_callback_query_safely(
            update, "未识别的积分商城操作，请刷新页面后重试", show_alert=True
        )
