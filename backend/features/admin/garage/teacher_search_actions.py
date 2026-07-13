from __future__ import annotations

from backend.features.admin.support import *


class TeacherSearchActionsMixin:
    async def _handle_teacher_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
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
        if action == "attendance" and callback_data.get(2) == "manual":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type=ConversationStateType.teacher_search_attendance_target_input.value,
                payload={"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📝 手动替老师打卡\n\n👉 请输入上牌老师的用户名或ID：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        if action == "attendance_mode":
            sub_action = callback_data.get(2)
            if sub_action == "menu":
                await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
                return
            if sub_action == "set":
                mode = callback_data.get(4)
            else:
                mode = callback_data.get(3)
            if mode not in {"external", "message", "keyword"}:
                await answer_callback_query_safely(update, "无效打卡模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, attendance_mode=mode)
                await session.commit()
            await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
            return
        if action == "attendance_source":
            sub_action = callback_data.get(2)
            if sub_action == "menu":
                await self._show_teacher_search_attendance_source_menu(update, context, chat_id)
                return
            if sub_action == "set":
                source_chat_id = callback_data.get_int_optional(4)
                if source_chat_id is None or source_chat_id == chat_id:
                    await answer_callback_query_safely(update, "无效打卡群", show_alert=True)
                    return
                allowed, error_text = await PermissionPolicyService.require_manage(
                    context,
                    source_chat_id,
                    update.effective_user.id,
                    capability="manage",
                )
                if not allowed:
                    await answer_callback_query_safely(update, error_text or "你没有该群组的管理权限", show_alert=True)
                    return
                await self._show_teacher_search_attendance_source_mode_menu(update, context, chat_id, source_chat_id=source_chat_id)
                return
        if action == "attendance_source_mode":
            sub_action = callback_data.get(2)
            if sub_action == "set":
                source_chat_id = callback_data.get_int_optional(4)
                mode = callback_data.get(5)
                if source_chat_id is None or source_chat_id == chat_id:
                    await answer_callback_query_safely(update, "无效打卡群", show_alert=True)
                    return
                if mode not in {"message", "keyword"}:
                    await answer_callback_query_safely(update, "无效打卡模式", show_alert=True)
                    return
                allowed, error_text = await PermissionPolicyService.require_manage(
                    context,
                    source_chat_id,
                    update.effective_user.id,
                    capability="manage",
                )
                if not allowed:
                    await answer_callback_query_safely(update, error_text or "你没有该群组的管理权限", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await TeacherSearchService.update_setting(
                        session,
                        chat_id,
                        attendance_mode="external",
                        attendance_source_chat_id=source_chat_id,
                    )
                    await TeacherSearchService.update_setting(
                        session,
                        source_chat_id,
                        attendance_enabled=True,
                        attendance_mode=mode,
                    )
                    await session.commit()
                await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
                return
        if action == "attendance_word":
            kind = callback_data.get(2)
            state_map = {
                "open": (ConversationStateType.teacher_search_attendance_open_input.value, "开课词", "开课"),
                "full": (ConversationStateType.teacher_search_attendance_full_input.value, "满课词", "满课"),
                "rest": (ConversationStateType.teacher_search_attendance_rest_input.value, "休息词", "休息"),
            }
            item = state_map.get(kind)
            if item is None:
                await answer_callback_query_safely(update, "无效打卡词", show_alert=True)
                return
            state_type, label, example = item
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type=state_type,
                payload={"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                f"{label}配置\n\n👉 请输入新的{label}：\n例如：{example}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:attendance_mode:menu:{chat_id}")]]),
            )
            return
        if action == "footer" and callback_data.get(2) in {"menu", "input"}:
            await self._show_teacher_search_footer_menu(update, context, chat_id)
            return
        if action == "footer" and callback_data.get(2) == "text":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type=ConversationStateType.teacher_search_footer_text_input.value,
                payload={"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                (
                    "🔎 老师搜索 | 底部按钮\n\n"
                    "👉 请输入按钮名称，例如：老师搜索\n"
                    "输入 /clear 可清空底部按钮。"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:footer:menu:{chat_id}")]
                ]),
            )
            return
        if action == "footer" and callback_data.get(2) == "link":
            await answer_callback_query_safely(update, "底部按钮不需要配置链接，点击后会直接触发老师搜索。")
            await self._show_teacher_search_footer_menu(update, context, chat_id)
            return
        if action == "footer" and callback_data.get(2) == "clear":
            async with db.session_factory() as session:
                await TeacherSearchService.clear_footer_button_config(session, chat_id)
                await session.commit()
            await self._show_teacher_search_footer_menu(update, context, chat_id)
            return
        if action == "toggle":
            field = callback_data.get(2)
            value = callback_data.get_int_optional(4)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            field_map = {
                "tag": "tag_search_enabled",
                "only_open": "only_open_course_enabled",
                "nearby": "nearby_search_enabled",
                "attendance": "attendance_enabled",
                "force_loc": "force_location_enabled",
            }
            setting_field = field_map.get(field)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            updates = {setting_field: bool(value)}
            if field == "force_loc" and value == 1:
                updates["nearby_search_enabled"] = True
            if field == "nearby" and value == 0:
                updates["force_location_enabled"] = False
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, **updates)
                await session.commit()
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
                state_type=ConversationStateType.teacher_search_delegate_target_input.value,
                payload={"target_chat_id": chat_id},
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
                page=callback_data.get_int_optional(4) or 0,
            )
            return
        await self._show_teacher_search_menu(update, context, chat_id)
