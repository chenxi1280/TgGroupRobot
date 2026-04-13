from __future__ import annotations

from backend.features.admin.support import *

class PointsLevelAdminControllerMixin:
    async def _handle_points_level(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击右侧按钮进行配置")
            return
        db: Database = context.application.bot_data["db"]
        if op == "toggle":
            field = callback_data.get(4)
            value = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
                if field == "enabled":
                    await PointsExtendedService.update_level_setting(session, setting, enabled=value)
                elif field == "exclude_teacher":
                    await PointsExtendedService.update_level_setting(session, setting, exclude_teacher_enabled=value)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "add":
            async with db.session_factory() as session:
                level = await PointsExtendedService.create_level(session, chat_id)
                await session.commit()
            await self._show_points_level_detail(update, context, chat_id, level.id)
            return
        if op == "detail":
            await self._show_points_level_detail(update, context, chat_id, callback_data.get_int(4))
            return
        if op == "edit":
            field = callback_data.get(4)
            level_id = callback_data.get_int(5)
            state_type = "points_level_name_input" if field == "name" else "points_level_threshold_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "level_id": level_id},
                )
                await session.commit()
            prompt = "👉 请输入新的等级名称：" if field == "name" else "👉 请输入新的积分门槛："
            await self.message_helper.safe_edit(update, text=prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")]]))
            return
        if op == "perm":
            level_id = callback_data.get_int(4)
            perm = callback_data.get(5)
            perm_value = bool(callback_data.get_int(6))
            async with db.session_factory() as session:
                level = await PointsExtendedService.get_level(session, chat_id, level_id)
                if level is not None:
                    await PointsExtendedService.update_level(session, level, perm_name=perm, perm_value=perm_value)
                await session.commit()
            await self._show_points_level_detail(update, context, chat_id, level_id)
            return
        if op == "delete":
            level_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                levels = await PointsExtendedService.list_levels(session, chat_id)
                if len(levels) <= 1:
                    await session.commit()
                    await answer_callback_query_safely(update, "至少保留一个等级，无法删除", show_alert=True)
                    await self._show_points_level_detail(update, context, chat_id, level_id)
                    return
                level = await PointsExtendedService.get_level(session, chat_id, level_id)
                if level is not None:
                    await PointsExtendedService.delete_level(session, level)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "delete_confirm":
            await self._show_points_level_delete_confirm(update, context, chat_id, callback_data.get_int(4))
            return
        await answer_callback_query_safely(update, "未识别的积分等级操作，请刷新页面后重试", show_alert=True)

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
                    "fulfiller": ("points_mall_product_fulfiller_input", "👉 请输入发放人员用户名或用户ID（输入 清空 取消设置）："),
                    "description": ("points_mall_product_description_input", "👉 请输入兑换说明（输入 清空 清空说明）："),
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

    async def _show_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分设置菜单"""
        from backend.features.admin.ui.points import points_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        all_enabled = bool(settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled)
        text = (
            f"💰 [{chat_title}] 主积分\n\n"
            f"状态：{'✅ 启动' if all_enabled else '❌ 关闭'}\n"
            f"签到：{'✅ 启动' if settings.sign_enabled else '❌ 关闭'}｜{settings.sign_points}分\n"
            f"发言：{'✅ 启动' if settings.message_points_enabled else '❌ 关闭'}｜{settings.message_points}分\n"
            f"邀请：{'✅ 启动' if settings.invite_points_enabled else '❌ 关闭'}｜{settings.invite_points}分\n\n"
            "已支持签到、发言、邀请、转让、管理员加减分、日志导出与清空积分。"
        )

        keyboard = points_config_keyboard(settings, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_custom_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自定义积分列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            items = await PointsExtendedService.list_custom_point_types(session, chat_id)
            await session.commit()

        lines = [
            "🌐 自定义积分",
            "",
            "可以创建多种积分类型，但是此积分只能通过管理员进行加减，使用场景：诚心分、贡献值等！",
            "",
        ]
        if items:
            for item in items:
                lines.extend(
                    [
                        f"{item.name}（状态：{'✅ 启用' if item.enabled else '❌ 关闭'}）",
                        f"└编号：{item.type_no}",
                        "",
                    ]
                )
            lines.append(f"{len(items)} 条数据，第 1 页/共 1 页")
        else:
            lines.append("0 条数据，第 1 页/共 1 页")

        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=custom_points_list_keyboard(items, chat_id),
        )

    async def _show_custom_points_add_entry(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：添加后进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await PointsExtendedService.create_custom_point_type(session, chat_id, update.effective_user.id)
            await session.commit()
        await self._show_custom_point_detail(update, context, chat_id, item.id)

    async def _show_points_level_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分等级列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
            levels = await PointsExtendedService.list_levels(session, chat_id)
            await session.commit()

        level_lines = []
        if levels:
            for level in levels:
                perms = [
                    f"文字{'✅' if level.allow_text else '❌'}",
                    f"音频{'✅' if level.allow_audio else '❌'}",
                    f"图片{'✅' if level.allow_photo else '❌'}",
                    f"视频{'✅' if level.allow_video else '❌'}",
                    f"贴纸{'✅' if level.allow_sticker else '❌'}",
                    f"文件{'✅' if level.allow_document else '❌'}",
                    f"提到{'✅' if level.allow_mention else '❌'}",
                ]
                level_lines.extend([f"{level.level_name}（积分门槛线 > {level.point_threshold}）", "└" + " ".join(perms), ""])
        else:
            level_lines.append("待配置（积分门槛线 > 0）")
            level_lines.append("")
        total_pages = 1
        text = "\n".join(
            [
                "👨‍💻 积分等级",
                "",
                "通过主积分数量划分用户等级，并设置不同等级的权限",
                "",
                *level_lines,
                f"{len(levels)} 条数据，第 1 页/共 {total_pages} 页",
            ]
        )

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_level_list_keyboard(setting, levels, chat_id),
        )

    async def _show_points_level_add_entry(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：创建等级并进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.create_level(session, chat_id)
            await session.commit()
        await self._show_points_level_detail(update, context, chat_id, level.id)

