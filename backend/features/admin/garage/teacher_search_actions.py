from __future__ import annotations

from backend.features.admin.support import *


class TeacherSearchActionsMixin:
    async def _start_teacher_search_input(
        self, update, context, *, chat_id: int, state_type, prompt: str,
        back_callback: str,
    ) -> None:
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=state_type, payload={"target_chat_id": chat_id},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=back_callback)]]
        )
        await self.message_helper.safe_edit(update, prompt, reply_markup=keyboard)

    async def _handle_teacher_attendance(
        self, update, context, *, enum, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "attendance":
            return False
        sub = callback_data.get(2)
        if sub == "menu":
            await self._show_teacher_search_attendance_menu(update, context, chat_id)
            return True
        if sub != "manual":
            return False
        await self._start_teacher_search_input(
            update, context, chat_id=chat_id,
            state_type=enum.teacher_search_attendance_target_input.value,
            prompt="📝 手动替老师打卡\n\n👉 请输入上牌老师的用户名或ID：",
            back_callback=f"tsearch:home:{chat_id}",
        )
        return True

    async def _handle_attendance_mode(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "attendance_mode":
            return False
        if callback_data.get(2) == "menu":
            await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
            return True
        mode_index = 4 if callback_data.get(2) == "set" else 3
        mode = callback_data.get(mode_index)
        if mode not in {"external", "message", "keyword"}:
            await answer_callback_query_safely(update, "无效打卡模式", show_alert=True)
            return True
        async with db.session_factory() as session:
            await service.update_setting(session, chat_id, attendance_mode=mode)
            await session.commit()
        await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
        return True

    async def _require_source_permission(
        self, update, context, *, chat_id: int, source_chat_id: int | None
    ) -> bool:
        if source_chat_id is None or source_chat_id == chat_id:
            await answer_callback_query_safely(update, "无效打卡群", show_alert=True)
            return False
        allowed, error = await PermissionPolicyService.require_manage(
            context, source_chat_id, update.effective_user.id, capability="manage"
        )
        if not allowed:
            await answer_callback_query_safely(
                update, error or "你没有该群组的管理权限", show_alert=True
            )
        return allowed

    async def _handle_attendance_source(
        self, update, context, *, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "attendance_source":
            return False
        if callback_data.get(2) == "menu":
            await self._show_teacher_search_attendance_source_menu(
                update, context, chat_id
            )
            return True
        if callback_data.get(2) != "set":
            return False
        source_id = callback_data.get_int_optional(4)
        if not await self._require_source_permission(
            update, context, chat_id=chat_id, source_chat_id=source_id
        ):
            return True
        await self._show_teacher_search_attendance_source_mode_menu(
            update, context, chat_id, source_chat_id=source_id
        )
        return True

    async def _handle_attendance_source_mode(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "attendance_source_mode":
            return False
        if callback_data.get(2) != "set":
            return False
        source_id = callback_data.get_int_optional(4)
        mode = callback_data.get(5)
        if mode not in {"message", "keyword"}:
            await answer_callback_query_safely(update, "无效打卡模式", show_alert=True)
            return True
        if not await self._require_source_permission(
            update, context, chat_id=chat_id, source_chat_id=source_id
        ):
            return True
        async with db.session_factory() as session:
            await service.update_setting(
                session, chat_id, attendance_mode="external",
                attendance_source_chat_id=source_id,
            )
            await service.update_setting(
                session, source_id, attendance_enabled=True, attendance_mode=mode
            )
            await session.commit()
        await self._show_teacher_search_attendance_mode_menu(update, context, chat_id)
        return True

    async def _handle_attendance_word(
        self, update, context, *, enum, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "attendance_word":
            return False
        configs = {
            "open": (enum.teacher_search_attendance_open_input.value, "开课词", "开课"),
            "full": (enum.teacher_search_attendance_full_input.value, "满课词", "满课"),
            "rest": (enum.teacher_search_attendance_rest_input.value, "休息词", "休息"),
        }
        config = configs.get(callback_data.get(2))
        if config is None:
            await answer_callback_query_safely(update, "无效打卡词", show_alert=True)
            return True
        await self._start_teacher_search_input(
            update, context, chat_id=chat_id, state_type=config[0],
            prompt=f"{config[1]}配置\n\n👉 请输入新的{config[1]}：\n例如：{config[2]}",
            back_callback=f"tsearch:attendance_mode:menu:{chat_id}",
        )
        return True

    async def _handle_teacher_search_footer(
        self, update, context, *, db, service, enum, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "footer":
            return False
        sub = callback_data.get(2)
        if sub in {"menu", "input"}:
            await self._show_teacher_search_footer_menu(update, context, chat_id)
            return True
        if sub == "text":
            await self._start_teacher_search_input(
                update, context, chat_id=chat_id,
                state_type=enum.teacher_search_footer_text_input.value,
                prompt="🔎 老师搜索 | 底部按钮\n\n👉 请输入按钮名称，例如：老师搜索\n输入 /clear 可清空底部按钮。",
                back_callback=f"tsearch:footer:menu:{chat_id}",
            )
            return True
        if sub == "link":
            await answer_callback_query_safely(
                update, "底部按钮不需要配置链接，点击后会直接触发老师搜索。"
            )
        elif sub == "clear":
            async with db.session_factory() as session:
                await service.clear_footer_button_config(session, chat_id)
                await session.commit()
        else:
            return False
        await self._show_teacher_search_footer_menu(update, context, chat_id)
        return True

    async def _handle_teacher_search_toggle(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "toggle":
            return False
        value = callback_data.get_int_optional(4)
        if value not in {0, 1}:
            await answer_callback_query_safely(update, "无效开关值", show_alert=True)
            return True
        fields = {
            "tag": "tag_search_enabled", "only_open": "only_open_course_enabled",
            "nearby": "nearby_search_enabled", "attendance": "attendance_enabled",
            "force_loc": "force_location_enabled",
        }
        field = callback_data.get(2)
        setting_field = fields.get(field)
        if setting_field is None:
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return True
        updates = {setting_field: bool(value)}
        if field == "force_loc" and value == 1:
            updates["nearby_search_enabled"] = True
        if field == "nearby" and value == 0:
            updates["force_location_enabled"] = False
        async with db.session_factory() as session:
            await service.update_setting(session, chat_id, **updates)
            await session.commit()
        await self._show_teacher_search_menu(update, context, chat_id)
        return True

    async def _handle_teacher_search_misc(
        self, update, context, *, db, service, enum, chat_id: int, callback_data
    ) -> bool:
        action = callback_data.get(1)
        if action == "delete_mode":
            mode = callback_data.get(3)
            if mode not in {"none", "delete"}:
                await answer_callback_query_safely(update, "无效删除策略", show_alert=True)
                return True
            async with db.session_factory() as session:
                await service.update_setting(session, chat_id, delete_mode=mode)
                await session.commit()
            await self._show_teacher_search_menu(update, context, chat_id)
            return True
        if action == "delegate" and callback_data.get(2) == "start":
            await self._start_teacher_search_input(
                update, context, chat_id=chat_id,
                state_type=enum.teacher_search_delegate_target_input.value,
                prompt="📍 代替老师录入位置\n\n👉 请输入上牌老师的用户名或ID：",
                back_callback=f"tsearch:home:{chat_id}",
            )
            return True
        if action != "open_course" or callback_data.get(2) != "list":
            return False
        await self._show_teacher_search_open_course_menu(
            update, context, chat_id, page=callback_data.get_int_optional(4) or 0
        )
        return True

    async def _handle_teacher_search(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService
        from backend.platform.db.schema.models.enums import ConversationStateType

        if callback_data.get(1) == "home":
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        db: Database = context.application.bot_data["db"]
        handlers = (
            (self._handle_teacher_attendance, {"enum": ConversationStateType}),
            (self._handle_attendance_mode, {"db": db, "service": TeacherSearchService}),
            (self._handle_attendance_source, {}),
            (self._handle_attendance_source_mode, {"db": db, "service": TeacherSearchService}),
            (self._handle_attendance_word, {"enum": ConversationStateType}),
            (self._handle_teacher_search_footer, {"db": db, "service": TeacherSearchService, "enum": ConversationStateType}),
            (self._handle_teacher_search_toggle, {"db": db, "service": TeacherSearchService}),
            (self._handle_teacher_search_misc, {"db": db, "service": TeacherSearchService, "enum": ConversationStateType}),
        )
        for handler, dependencies in handlers:
            if await handler(
                update, context, chat_id=chat_id,
                callback_data=callback_data, **dependencies,
            ):
                return
        await self._show_teacher_search_menu(update, context, chat_id)
