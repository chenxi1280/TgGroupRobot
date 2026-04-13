from __future__ import annotations

from backend.features.admin.support import *

class PointsMallAdminControllerMixin:
    async def _show_points_mall_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城主配置页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "🏦 积分商城",
                "",
                "用户可以使用积分兑换商品，增加积分价值，促进群活跃。",
                "",
                f"指令：群里输入 {setting.entry_command} 唤起商品列表",
            ]
        )

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_home_keyboard(setting, chat_id),
        )

    async def _show_points_mall_cover_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城封面页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await session.commit()
        text = (
            "🛍️ 积分商城 | 商城封面\n\n"
            f"当前封面：{'未设置' if not setting.cover_file_id else '已设置'}"
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_cover_keyboard(chat_id),
        )

    async def _show_points_mall_command_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城修改指令页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
            await set_user_state(
                session,
                chat_id=update.effective_user.id,
                user_id=update.effective_user.id,
                state_type="points_mall_command_input",
                state_data={"target_chat_id": chat_id},
            )
            await session.commit()
        text = (
            "⚙️ 积分商城 | 修改指令\n\n"
            f"当前指令：{setting.entry_command}\n\n"
            "👉 现在输入新的指令："
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_command_keyboard(chat_id),
        )

    async def _show_points_mall_products_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分商城商品管理页"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            products = await PointsExtendedService.list_products(session, chat_id)
            await session.commit()
        if products:
            chunks: list[str] = ["🛍️ 管理商品 | 商品列表", ""]
            for product in products:
                chunks.extend(
                    [
                        f"商品名称：{product.name}",
                        f"顺序编号：{product.product_id}（排序权重{product.sort_weight}）",
                        f"兑换价格：{product.price_points}",
                        f"可售数量：{product.stock_left}/{product.stock_total}",
                        f"上架状态：{'✅' if product.status == 'on_sale' else '❌'}",
                        "",
                    ]
                )
            chunks.append(f"{len(products)} 条数据，第 1 页/共 1 页")
            text = "\n".join(chunks)
        else:
            text = "🛍️ 管理商品 | 商品列表\n\n0 条数据，第 1 页/共 1 页"
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_products_keyboard(products, chat_id),
        )

    async def _show_points_mall_orders_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int | None = None,
        status: str = "all",
    ) -> None:
        """显示积分商城订单管理页"""
        normalized_status = status if status in {"all", "created", "fulfilled", "canceled", "refunded"} else "all"
        status_name_map = {
            "all": "全部",
            "created": "待处理",
            "fulfilled": "已发放",
            "canceled": "已取消",
            "refunded": "已退款",
        }
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            orders = await PointsExtendedService.list_recent_orders(
                session,
                chat_id,
                limit=20,
                product_id=product_id,
                order_status=normalized_status,
            )
            status_counts = await PointsExtendedService.count_orders_by_status(
                session,
                chat_id=chat_id,
                product_id=product_id,
            )
            await session.commit()
        summary = (
            f"📊 全部 {status_counts.get('all', 0)}"
            f"｜🟡 待处理 {status_counts.get('created', 0)}"
            f"｜✅ 已发放 {status_counts.get('fulfilled', 0)}"
            f"｜❌ 已取消 {status_counts.get('canceled', 0)}"
            f"｜💸 已退款 {status_counts.get('refunded', 0)}"
        )
        if orders:
            title = "🧾 管理订单" if product_id is None else f"🧾 管理订单 | 商品 {product_id}"
            lines = [title, f"当前筛选：{status_name_map.get(normalized_status, '全部')}", summary, ""]
            for order in orders:
                lines.extend(
                    [
                        f"订单#{order.order_id}｜商品 {order.product_id}",
                        f"用户：{order.buyer_user_id}",
                        f"积分：{order.price_points}｜数量：{order.quantity}",
                        f"状态：{order.order_status}",
                        "",
                    ]
                )
            lines.append(f"{len(orders)} 条数据，第 1 页/共 1 页")
            text = "\n".join(lines)
        else:
            text = (
                f"🧾 管理订单\n当前筛选：{status_name_map.get(normalized_status, '全部')}\n{summary}\n\n0 条数据，第 1 页/共 1 页"
                if product_id is None
                else f"🧾 管理订单 | 商品 {product_id}\n当前筛选：{status_name_map.get(normalized_status, '全部')}\n{summary}\n\n0 条数据，第 1 页/共 1 页"
            )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_orders_keyboard(
                chat_id,
                orders=orders,
                product_id=product_id,
                status=normalized_status,
                status_counts=status_counts,
            ),
        )

    async def _show_points_mall_order_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        order_id: int,
        *,
        status: str = "all",
        product_id: int | None = None,
    ) -> None:
        normalized_status = status if status in {"all", "created", "fulfilled", "canceled", "refunded"} else "all"
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            order = await PointsExtendedService.get_order(session, chat_id, order_id)
            logs = await PointsExtendedService.list_order_logs(session, order_id=order_id, limit=5)
            await session.commit()
        if order is None:
            await answer_callback_query_safely(update, "订单不存在", show_alert=True)
            await self._show_points_mall_orders_page(update, context, chat_id, product_id=product_id, status=normalized_status)
            return
        log_lines = ["最近操作："]
        if not logs:
            log_lines.append("- 暂无日志")
        else:
            for item in logs:
                payload = item.payload or {}
                operator = payload.get("operator_user_id", "-")
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                log_lines.append(f"- {timestamp}｜{item.action}｜操作人 {operator}")
        text = "\n".join(
            [
                "🧾 管理订单 | 订单详情",
                "",
                f"订单编号：{order.order_id}",
                f"商品编号：{order.product_id}",
                f"购买用户：{order.buyer_user_id}",
                f"所需积分：{order.price_points}",
                f"数量：{order.quantity}",
                f"订单状态：{order.order_status}",
                f"操作人员：{order.operator_user_id or '未处理'}",
                "",
                *log_lines,
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_order_detail_keyboard(
                chat_id,
                order,
                status=normalized_status,
                product_id=product_id,
            ),
        )

    async def _show_custom_point_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        type_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
            await session.commit()
        if item is None:
            await answer_callback_query_safely(update, "❌ 记录不存在", show_alert=True)
            await self._show_custom_points_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🌐 自定义积分",
                "",
                f"状态：{'✅ 启用' if item.enabled else '❌ 关闭'}",
                f"⚙️ 积分名字： {item.name}",
                f"⚙️ 排行指令： {item.rank_command or '待配置'}",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=custom_point_detail_keyboard(item, chat_id))

    async def _show_points_level_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        level_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.get_level(session, chat_id, level_id)
            await session.commit()
        if level is None:
            await answer_callback_query_safely(update, "❌ 等级不存在", show_alert=True)
            await self._show_points_level_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "👨‍💻 积分等级 | 配置等级信息",
                "",
                "通过各种激励方法，促进群友持续水群发言",
                "",
                f"等级名称：{level.level_name}",
                f"积分门槛线：{level.point_threshold}",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=points_level_detail_keyboard(level, chat_id))

    async def _show_points_level_delete_confirm(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        level_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.get_level(session, chat_id, level_id)
            await session.commit()
        if level is None:
            await answer_callback_query_safely(update, "❌ 等级不存在", show_alert=True)
            await self._show_points_level_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "👨‍💻 积分等级 | 删除等级",
                "",
                f"等级名称：{level.level_name}",
                f"积分门槛线：{level.point_threshold}",
                "",
                "确认后将删除当前等级。",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("确认删除", callback_data=f"adm:lvl:{chat_id}:delete:{level_id}")],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")],
                ]
            ),
        )

    async def _show_points_mall_product_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            await session.commit()
        if product is None:
            await answer_callback_query_safely(update, "❌ 商品不存在", show_alert=True)
            await self._show_points_mall_products_page(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🛍️ 管理商品 | 编辑商品",
                "",
                f"🎁 商品名称： {product.name}",
                f"🖼️ 封面设置： {'未设置' if not product.cover_file_id else '已设置'}",
                f"🪙 兑换价格： {product.price_points}",
                f"📮 限购设置： {'不限制' if not product.limit_per_user else product.limit_per_user}",
                f"🛒 可售数量： {product.stock_left}/{product.stock_total}",
                f"👨 商品发放： {product.fulfiller_user_id or '未设置'}",
                f"↕️ 排序权重： {product.sort_weight}",
                f"⚠️ 兑换说明： {'未设置' if not product.description else '已设置'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_mall_product_detail_keyboard(product, chat_id),
        )

    async def _show_points_mall_product_preview(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        product_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            product = await PointsExtendedService.get_product(session, chat_id, product_id)
            await session.commit()
        if product is None:
            await answer_callback_query_safely(update, "❌ 商品不存在", show_alert=True)
            await self._show_points_mall_products_page(update, context, chat_id)
            return
        text = "\n".join(
            [
                "🛍️ 管理商品 | 预览效果",
                "",
                f"商品名称：{product.name}",
                f"兑换价格：{product.price_points} 积分",
                f"限购设置：{'不限制' if not product.limit_per_user else product.limit_per_user}",
                f"可售数量：{product.stock_left}/{product.stock_total}",
                f"兑换说明：{product.description or '暂无说明'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:mall:{chat_id}:product:detail:{product_id}")]]
            ),
        )

