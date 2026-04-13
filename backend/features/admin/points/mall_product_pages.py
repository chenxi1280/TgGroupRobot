from __future__ import annotations

from backend.features.admin.support import *


class PointsMallProductPagesMixin:
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
