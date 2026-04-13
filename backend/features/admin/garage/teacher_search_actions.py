from __future__ import annotations

from backend.features.admin.support import *


class TeacherSearchActionsMixin:
    async def _handle_teacher_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "attendance" and callback_data.get(2) == "menu":
            await self._show_teacher_search_attendance_menu(update, context, chat_id)
            return
        if action == "toggle":
            field = callback_data.get(2)
            value = callback_data.get_int_optional(4)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            field_map = {
                "tag": "tag_search_enabled",
                "nearby": "nearby_search_enabled",
                "attendance": "attendance_enabled",
                "force_loc": "force_location_enabled",
            }
            setting_field = field_map.get(field)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, **{setting_field: bool(value)})
                await session.commit()
            if field == "force_loc":
                await self._show_teacher_search_attendance_menu(update, context, chat_id)
            else:
                await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delete_mode":
            mode = callback_data.get(3)
            if mode not in {"none", "delete"}:
                await answer_callback_query_safely(update, "无效删除策略", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, delete_mode=mode)
                await session.commit()
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delegate" and callback_data.get(2) == "start":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.teacher_search_delegate_target_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📍 代替老师录入位置\n\n👉 请输入上牌老师的用户名或ID：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        if action == "open_course" and callback_data.get(2) == "list":
            await self._show_teacher_search_open_course_menu(
                update,
                context,
                chat_id,
                callback_data.get_int_optional(4) or 0,
            )
            return
        await self._show_teacher_search_menu(update, context, chat_id)
