from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_time_keyboard, build_hhmm_prompt_text, next_top_of_hour_hhmm


class ModerationControlActionsMixin:
    async def _handle_permission_policy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
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
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType, GroupLockDeleteNoticeMode

        op = callback_data.get(3)
        arg = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "phrase":
                    settings.group_lock_phrase_enabled = not bool(settings.group_lock_phrase_enabled)
                elif arg == "schedule":
                    settings.group_lock_schedule_enabled = not bool(settings.group_lock_schedule_enabled)
                elif arg == "delete_notice":
                    current = getattr(settings, "group_lock_delete_notice_mode", GroupLockDeleteNoticeMode.keep.value)
                    settings.group_lock_delete_notice_mode = (
                        GroupLockDeleteNoticeMode.delete.value
                        if current != GroupLockDeleteNoticeMode.delete.value
                        else GroupLockDeleteNoticeMode.keep.value
                    )
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "set":
            value = callback_data.get_int_optional(5)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "phrase":
                    settings.group_lock_phrase_enabled = bool(value)
                elif arg == "schedule":
                    settings.group_lock_schedule_enabled = bool(value)
                else:
                    await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                    return
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "notice":
            mode = callback_data.get(4)
            if mode not in {GroupLockDeleteNoticeMode.delete.value, GroupLockDeleteNoticeMode.keep.value}:
                await answer_callback_query_safely(update, "无效通知策略", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.group_lock_delete_notice_mode = mode
                await session.commit()
            await self._show_group_lock_menu(update, context, chat_id)
            return

        if op == "input":
            state_map = {
                "open_phrase": ConversationStateType.group_lock_open_keyword_input.value,
                "close_phrase": ConversationStateType.group_lock_close_keyword_input.value,
                "open_time": ConversationStateType.group_lock_open_time_input.value,
                "close_time": ConversationStateType.group_lock_close_time_input.value,
            }
            state_type = state_map.get(arg)
            if state_type is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type,
                {"target_chat_id": chat_id},
            )
            if arg in {"open_time", "close_time"}:
                sample_text = next_top_of_hour_hhmm(hours_offset=0 if arg == "open_time" else 8)
                title = "🔓 定时开关群 | 编辑开群时间" if arg == "open_time" else "🔒 定时开关群 | 编辑关群时间"
                hint = "👉 请输入开群时间（格式 HH:MM）： " if arg == "open_time" else "👉 请输入关群时间（格式 HH:MM）： "
                await self.message_helper.safe_edit(
                    update,
                    build_hhmm_prompt_text(
                        title=title,
                        sample_time_text=sample_text,
                        input_hint=hint.strip(),
                    ),
                    parse_mode="HTML",
                    reply_markup=build_copy_time_keyboard(f"adm:menu:closegroup:{chat_id}", sample_text),
                )
                return
            prompt = {
                "open_phrase": "👉 请输入新的开群词：",
                "close_phrase": "👉 请输入新的关群词：",
            }[arg]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:closegroup:{chat_id}")]]),
            )

    async def _handle_rename_monitor(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        op = callback_data.get(3)
        arg = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.name_change_monitor_enabled = not bool(getattr(settings, "name_change_monitor_enabled", False))
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)
            return

        if op == "set" and arg == "enabled":
            value = callback_data.get_int_optional(5)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.name_change_monitor_enabled = bool(value)
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)
            return

        if op == "input" and arg == "text":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                template_text = getattr(settings, "name_change_monitor_template_text", "") or (
                    "检测到用户{userId}修改{changeType}\n"
                    "原{changeType}: {oldContent}\n"
                    "新{changeType}: {newContent}\n\n"
                    "请注意规避风险"
                )
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.rename_monitor_text_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                (
                    "🕵️ 用户改名监控 | 修改文案\n\n"
                    f"当前文案：{template_text}\n\n"
                    "替换符\n"
                    "└ {changeType} = 改变的类型\n"
                    "└ {oldContent} = 改变前内容\n"
                    "└ {newContent} = 改变后内容\n"
                    "└ {userId} = 用户id\n\n"
                    "👉 现在输入新的文案内容："
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]]),
            )
            return

        if op == "preview":
            preview = (
                "检测到用户123456修改昵称\n"
                "原昵称: 老名字\n"
                "新昵称: 新名字\n\n"
                "请注意规避风险"
            )
            await answer_callback_query_safely(update, "已生成预览", show_alert=False)
            await self.message_helper.safe_edit(
                update,
                preview,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:renamewatch:{chat_id}")]]),
            )
            return

        if op in {"delete_after", "cycle_delete_after"}:
            seconds = callback_data.get_int_optional(4)
            options = [15, 30, 60, 90]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)
                if seconds is None:
                    next_seconds = options[(options.index(current) + 1) % len(options)] if current in options else 60
                else:
                    next_seconds = seconds
                settings.name_change_monitor_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_rename_monitor_menu(update, context, chat_id)
