from __future__ import annotations

from backend.features.admin.support import *


class PointsMallBasePagesMixin:
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
