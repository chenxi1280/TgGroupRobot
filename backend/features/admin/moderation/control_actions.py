from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_time_keyboard, build_hhmm_prompt_text, next_top_of_hour_hhmm


def _toggle_group_lock_setting(settings, option: str, *, delete_value: str, keep_value: str) -> bool:
    if option == "phrase":
        settings.group_lock_phrase_enabled = not bool(settings.group_lock_phrase_enabled)
        return True
    if option == "schedule":
        settings.group_lock_schedule_enabled = not bool(settings.group_lock_schedule_enabled)
        return True
    if option != "delete_notice":
        return False
    current = getattr(settings, "group_lock_delete_notice_mode", keep_value)
    settings.group_lock_delete_notice_mode = delete_value if current != delete_value else keep_value
    return True


class ModerationControlActionsMixin:
    async def _handle_permission_policy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ControlPermissionPolicy

        value = callback_data.get(3)
        if value not in {item.value for item in ControlPermissionPolicy}:
            await answer_callback_query_safely(update, "无效权限策略", show_alert=True)
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            settings.control_permission_policy = value
            await session.commit()

        await self._show_control_permission_menu(update, context, chat_id)

    async def _handle_group_lock(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        arg = callback_data.get(4)
        if op == "toggle":
            await self._toggle_group_lock(update, context, chat_id, option=arg)
            return
        if op == "set":
            await self._set_group_lock(update, context, chat_id, option=arg, value=callback_data.get_int_optional(5))
            return
        if op == "notice":
            await self._set_group_lock_notice(update, context, chat_id, mode=arg)
            return
        if op == "input":
            await self._start_group_lock_input(update, context, chat_id, option=arg)
            return
        await answer_callback_query_safely(update, "无效操作", show_alert=True)

    async def _toggle_group_lock(self, update, context, chat_id: int, *, option: str) -> None:
        from backend.platform.db.schema.models.enums import GroupLockDeleteNoticeMode

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            changed = _toggle_group_lock_setting(
                settings,
                option,
                delete_value=GroupLockDeleteNoticeMode.delete.value,
                keep_value=GroupLockDeleteNoticeMode.keep.value,
            )
            if not changed:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            await session.commit()
        await self._show_night_mode_menu(update, context, chat_id)

    async def _set_group_lock(self, update, context, chat_id: int, *, option: str, value: int | None) -> None:
        if value not in {0, 1}:
            await answer_callback_query_safely(update, "无效开关值", show_alert=True)
            return
        attributes = {"phrase": "group_lock_phrase_enabled", "schedule": "group_lock_schedule_enabled"}
        attribute = attributes.get(option)
        if attribute is None:
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            setattr(settings, attribute, bool(value))
            await session.commit()
        await self._show_night_mode_menu(update, context, chat_id)

    async def _set_group_lock_notice(self, update, context, chat_id: int, *, mode: str) -> None:
        from backend.platform.db.schema.models.enums import GroupLockDeleteNoticeMode

        valid_modes = {GroupLockDeleteNoticeMode.delete.value, GroupLockDeleteNoticeMode.keep.value}
        if mode not in valid_modes:
            await answer_callback_query_safely(update, "无效通知策略", show_alert=True)
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            settings.group_lock_delete_notice_mode = mode
            await session.commit()
        await self._show_night_mode_menu(update, context, chat_id)

    async def _start_group_lock_input(self, update, context, chat_id: int, *, option: str) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        state_map = {
            "open_phrase": ConversationStateType.group_lock_open_keyword_input.value,
            "close_phrase": ConversationStateType.group_lock_close_keyword_input.value,
            "open_time": ConversationStateType.group_lock_open_time_input.value,
            "close_time": ConversationStateType.group_lock_close_time_input.value,
        }
        state_type = state_map.get(option)
        if state_type is None:
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_type,
            payload={"target_chat_id": chat_id},
        )
        if option in {"open_time", "close_time"}:
            await self._show_group_lock_time_prompt(update, chat_id, option=option)
            return
        prompt = {"open_phrase": "👉 请输入新的开群词：", "close_phrase": "👉 请输入新的关群词："}[option]
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:night:{chat_id}")]])
        await self.message_helper.safe_edit(update, prompt, reply_markup=markup)

    async def _show_group_lock_time_prompt(self, update, chat_id: int, *, option: str) -> None:
        is_open = option == "open_time"
        sample_text = next_top_of_hour_hhmm(hours_offset=0 if is_open else 8)
        title = "🌙 夜间管控 | 编辑结束时间" if is_open else "🌙 夜间管控 | 编辑开始时间"
        hint = "👉 请输入管控结束时间（格式 HH:MM）：" if is_open else "👉 请输入管控开始时间（格式 HH:MM）："
        await self.message_helper.safe_edit(
            update,
            build_hhmm_prompt_text(title=title, sample_time_text=sample_text, input_hint=hint),
            parse_mode="HTML",
            reply_markup=build_copy_time_keyboard(f"adm:menu:night:{chat_id}", sample_text),
        )

    async def _handle_rename_monitor(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        arg = callback_data.get(4)
        if op == "toggle":
            await self._set_rename_monitor_enabled(update, context, chat_id, value=None)
            return
        if op == "set" and arg == "enabled":
            await self._set_rename_monitor_enabled(update, context, chat_id, value=callback_data.get_int_optional(5))
            return
        if op == "input" and arg == "text":
            await self._start_rename_monitor_text_input(update, context, chat_id)
            return
        if op == "preview":
            await self._show_rename_monitor_preview(update, chat_id)
            return
        if op in {"delete_after", "cycle_delete_after"}:
            await self._set_rename_monitor_delete_after(
                update,
                context,
                chat_id,
                seconds=callback_data.get_int_optional(4),
            )
            return
        await answer_callback_query_safely(update, "无效操作", show_alert=True)

    async def _set_rename_monitor_enabled(self, update, context, chat_id: int, *, value: int | None) -> None:
        if value not in {None, 0, 1}:
            await answer_callback_query_safely(update, "无效开关值", show_alert=True)
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            current = bool(getattr(settings, "name_change_monitor_enabled", False))
            settings.name_change_monitor_enabled = not current if value is None else bool(value)
            await session.commit()
        await self._show_rename_monitor_menu(update, context, chat_id)

    async def _start_rename_monitor_text_input(self, update, context, chat_id: int) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            template_text = getattr(settings, "name_change_monitor_template_text", "") or (
                "检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n"
                "新{changeType}: {newContent}\n\n请注意规避风险"
            )
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=ConversationStateType.rename_monitor_text_input.value,
            payload={"target_chat_id": chat_id},
        )
        prompt = (
            "🕵️ 用户改名监控 | 修改文案\n\n"
            f"当前文案：{template_text}\n\n替换符\n"
            "└ {changeType} = 改变的类型\n└ {oldContent} = 改变前内容\n"
            "└ {newContent} = 改变后内容\n└ {userId} = 用户id\n\n👉 现在输入新的文案内容："
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]])
        await self.message_helper.safe_edit(update, prompt, reply_markup=markup)

    async def _show_rename_monitor_preview(self, update, chat_id: int) -> None:
        preview = "检测到用户123456修改昵称\n原昵称: 老名字\n新昵称: 新名字\n\n请注意规避风险"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]])
        await answer_callback_query_safely(update, "已生成预览", show_alert=False)
        await self.message_helper.safe_edit(update, preview, reply_markup=markup)

    async def _set_rename_monitor_delete_after(self, update, context, chat_id: int, *, seconds: int | None) -> None:
        options = [15, 30, 60, 90]
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            current = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)
            next_seconds = options[(options.index(current) + 1) % len(options)] if seconds is None and current in options else seconds
            settings.name_change_monitor_delete_after_seconds = next_seconds if next_seconds is not None else 60
            await session.commit()
        await self._show_rename_monitor_menu(update, context, chat_id)
