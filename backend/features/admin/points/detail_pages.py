from __future__ import annotations

from backend.features.admin.support import *


class PointsDetailPagesMixin:
    async def _show_custom_point_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, type_id: int,
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
        *, level_id: int,
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
        *, level_id: int,
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
