from __future__ import annotations

from backend.features.admin.support import *


class PointsLevelActionsMixin:
    async def _handle_points_level(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
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
                await PointsExtendedService.create_level(session, chat_id)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "detail":
            await self._show_points_level_detail(update, context, chat_id, level_id=callback_data.get_int(4))
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
            await self.message_helper.safe_edit(
                update,
                text=prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:lvl:{chat_id}:detail:{level_id}")]]),
            )
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
            await self._show_points_level_detail(update, context, chat_id, level_id=level_id)
            return
        if op == "delete":
            level_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                levels = await PointsExtendedService.list_levels(session, chat_id)
                if len(levels) <= 1:
                    await session.commit()
                    await answer_callback_query_safely(update, "至少保留一个等级，无法删除", show_alert=True)
                    await self._show_points_level_detail(update, context, chat_id, level_id=level_id)
                    return
                level = await PointsExtendedService.get_level(session, chat_id, level_id)
                if level is not None:
                    await PointsExtendedService.delete_level(session, level)
                await session.commit()
            await self._show_points_level_menu(update, context, chat_id)
            return
        if op == "delete_confirm":
            await self._show_points_level_delete_confirm(update, context, chat_id, level_id=callback_data.get_int(4))
            return
        await answer_callback_query_safely(update, "未识别的积分等级操作，请刷新页面后重试", show_alert=True)
