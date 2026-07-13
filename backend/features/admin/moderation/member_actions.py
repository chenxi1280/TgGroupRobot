from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import (
    build_copy_options_keyboard,
    build_copy_time_keyboard,
    build_hhmm_prompt_text,
    build_numeric_duration_prompt_text,
    next_top_of_hour_hhmm,
)


def _build_force_subscribe_delete_after_keyboard(chat_id: int, current_seconds: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    option_rows = [
        FORCE_SUBSCRIBE_DELETE_AFTER_VALUES[:3],
        FORCE_SUBSCRIBE_DELETE_AFTER_VALUES[3:],
    ]
    for option_row in option_rows:
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if seconds == current_seconds else ''}{seconds}秒",
                callback_data=f"adm:fs:{chat_id}:delete_after:{seconds}",
            )
            for seconds in option_row
        ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


class ModerationMemberActionsMixin:
    async def _handle_force_subscribe(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType, ForceSubscribeAction

        op = callback_data.get(3)
        arg = callback_data.get(4)
        if op == "toggle":
            field = "force_subscribe_custom_buttons_enabled" if arg == "buttons" else "force_subscribe_enabled"
            await self._toggle_member_setting(update, context, chat_id, field=field, menu="force_subscribe")
            return
        if op == "input":
            await self._start_force_subscribe_input(update, context, chat_id, option=arg, state_enum=ConversationStateType)
            return
        if op == "preview":
            await self._show_member_force_subscribe_preview(update, context, chat_id)
            return
        if op in {"delete_after", "cycle_delete_after"}:
            await self._handle_force_subscribe_delete_after(
                update,
                context,
                chat_id,
                seconds=callback_data.get_int_optional(4),
            )
            return
        if op == "cycle_check_mode":
            await self._cycle_force_subscribe_value(update, context, chat_id, field="force_subscribe_check_mode", options=["all", "any"])
            return
        if op == "cycle_action":
            options = [
                ForceSubscribeAction.delete_and_warn.value,
                ForceSubscribeAction.delete_only.value,
                ForceSubscribeAction.warn_only.value,
                ForceSubscribeAction.mute.value,
            ]
            await self._cycle_force_subscribe_value(
                update,
                context,
                chat_id,
                field="force_subscribe_not_subscribed_action",
                options=options,
            )
            return
        if op == "clear_cover":
            await self._clear_force_subscribe_cover(update, context, chat_id)
            return
        await answer_callback_query_safely(update, "未识别的强制关注操作，请返回后重试", show_alert=True)

    async def _toggle_member_setting(self, update, context, chat_id: int, *, field: str, menu: str) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            setattr(settings, field, not bool(getattr(settings, field, False)))
            await session.commit()
        menu_handler = {
            "force_subscribe": self._show_force_subscribe_menu,
            "new_member": self._show_new_member_limit_menu,
            "night": self._show_night_mode_menu,
        }[menu]
        await menu_handler(update, context, chat_id)

    async def _start_force_subscribe_input(self, update, context, chat_id: int, *, option: str, state_enum) -> None:
        state_map = {
            "channel1": state_enum.force_subscribe_channel_1_input.value,
            "channel2": state_enum.force_subscribe_channel_2_input.value,
            "text": state_enum.force_subscribe_text_input.value,
            "cover": state_enum.force_subscribe_cover_input.value,
            "buttons": state_enum.force_subscribe_buttons_input.value,
        }
        state_type = state_map.get(option)
        if state_type is None:
            await answer_callback_query_safely(update, "未识别的强制关注配置项，请返回后重试", show_alert=True)
            return
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_type,
            payload={"target_chat_id": chat_id},
        )
        prompt = self._force_subscribe_prompt(option)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")]])
        await self.message_helper.safe_edit(update, prompt, reply_markup=markup)

    @staticmethod
    def _force_subscribe_prompt(option: str) -> str:
        prompts = {
            "channel1": "👉 请回复需要绑定的频道1（频道id、用户名或链接）：",
            "channel2": "👉 请回复需要绑定的频道2（频道id、用户名或链接）：",
            "text": "👉 现在输入新的文案内容：",
            "cover": "👉 请发送图片或视频文件；发送“清空”可移除封面。",
            "buttons": (
                "👉 请输入按钮配置。\n支持两种格式：\n"
                "1) JSON：[[{\"text\":\"加入频道\",\"url\":\"https://t.me/example\"}]]\n"
                "2) 文本行：每行一个按钮，格式“按钮文案|https://t.me/example”\n发送“清空”可移除按钮。"
            ),
        }
        return prompts[option]

    async def _show_member_force_subscribe_preview(self, update, context, chat_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()
        text = "👀 强制关注 | 预览效果\n\n这是用户未关注频道/群组时会收到的提示样式预览。"
        markup = await _build_force_subscribe_preview_markup_async(settings, chat_id, context)
        await self.message_helper.safe_edit(update, text, reply_markup=markup)

    async def _handle_force_subscribe_delete_after(self, update, context, chat_id: int, *, seconds: int | None) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            current = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
            if seconds is None:
                await session.commit()
                markup = _build_force_subscribe_delete_after_keyboard(chat_id, current)
                await self.message_helper.safe_edit(update, "🕘 强制关注 | 删除提示消息\n\n请选择提示消息发送后多久自动删除。", reply_markup=markup)
                return
            if seconds not in FORCE_SUBSCRIBE_DELETE_AFTER_VALUES:
                await answer_callback_query_safely(update, "请选择列表中的时间", show_alert=True)
                return
            settings.force_subscribe_delete_warn_after_seconds = seconds
            await session.commit()
        await self._show_force_subscribe_menu(update, context, chat_id)

    async def _cycle_force_subscribe_value(self, update, context, chat_id: int, *, field: str, options: list[str]) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            current = getattr(settings, field, options[0])
            next_value = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
            setattr(settings, field, next_value)
            await session.commit()
        await self._show_force_subscribe_menu(update, context, chat_id)

    async def _clear_force_subscribe_cover(self, update, context, chat_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            settings.force_subscribe_cover_media_type = None
            settings.force_subscribe_cover_file_id = None
            await session.commit()
        await self._show_force_subscribe_menu(update, context, chat_id)

    async def _handle_new_member_limit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        op = callback_data.get(3)
        arg = callback_data.get(4)
        if op == "toggle":
            field_map = {
                "enabled": "new_member_limit_enabled",
                "block_media": "new_member_limit_block_media",
                "block_links": "new_member_limit_block_links",
                "text_only": "new_member_limit_text_only",
                "delete_message": "new_member_limit_delete_message",
                "warn_enabled": "new_member_limit_warn_enabled",
            }
            field = field_map.get(arg)
            if field is None:
                await answer_callback_query_safely(update, "未识别的新成员限制配置项，请返回后重试", show_alert=True)
                return
            await self._toggle_member_setting(update, context, chat_id, field=field, menu="new_member")
            return
        if op == "input":
            await self._start_new_member_input(update, context, chat_id, option=arg, state_enum=ConversationStateType)
            return
        if op == "cycle" and arg == "warn_delete":
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "new_member_limit_warn_delete_after_seconds", 60) or 60)
                next_seconds = _cycle_config_value(current, NEW_MEMBER_WARN_DELETE_VALUES)
                settings.new_member_limit_warn_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_new_member_limit_menu(update, context, chat_id)
            return
        await answer_callback_query_safely(update, "未识别的新成员限制操作，请返回后重试", show_alert=True)

    async def _start_new_member_input(self, update, context, chat_id: int, *, option: str, state_enum) -> None:
        if option not in {"window", "warn_text"}:
            await answer_callback_query_safely(update, "未识别的新成员限制输入项，请返回后重试", show_alert=True)
            return
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_enum.new_member_limit_text_input.value,
            payload={"target_chat_id": chat_id, "field": option},
        )
        if option == "window":
            await self._show_new_member_window_prompt(update, chat_id)
            return
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:newmem:{chat_id}")]])
        await self.message_helper.safe_edit(update, "👉 请输入提示文案：", reply_markup=markup)

    async def _show_new_member_window_prompt(self, update, chat_id: int) -> None:
        prompt = build_numeric_duration_prompt_text(
            title="🆕 新成员限制 | 限制时长",
            unit_label="分钟",
            sample_value_text="60",
            input_hint="👉 请输入限制时长（分钟）：",
        )
        markup = build_copy_options_keyboard(
            f"adm:menu:newmem:{chat_id}",
            [("📋 复制 60分钟", "60"), ("📋 复制 120分钟", "120")],
        )
        await self.message_helper.safe_edit(update, prompt, parse_mode="HTML", reply_markup=markup)

    async def _handle_night_mode(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        op = callback_data.get(3)
        arg = callback_data.get(4)
        if op == "toggle":
            field_map = {
                "enabled": "night_mode_enabled",
                "lock_schedule": "group_lock_schedule_enabled",
                "lock_phrase": "group_lock_phrase_enabled",
                "exempt_admin": "night_mode_exempt_admin",
                "delete_message": "night_mode_delete_message",
                "warn_enabled": "night_mode_warn_enabled",
            }
            field = field_map.get(arg)
            if field is None:
                await answer_callback_query_safely(update, "未识别的夜间管控配置项，请返回后重试", show_alert=True)
                return
            await self._toggle_member_setting(update, context, chat_id, field=field, menu="night")
            return
        if op == "notice":
            await self._set_night_notice(update, context, chat_id, mode=arg)
            return
        if op == "input":
            await self._start_night_input(update, context, chat_id, option=arg, state_enum=ConversationStateType)
            return
        if op == "cycle" and arg == "warn_delete":
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "night_mode_warn_delete_after_seconds", 60) or 60)
                next_seconds = _cycle_config_value(current, NEW_MEMBER_WARN_DELETE_VALUES)
                settings.night_mode_warn_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_night_mode_menu(update, context, chat_id)
            return
        await answer_callback_query_safely(update, "未识别的夜间管控操作，请返回后重试", show_alert=True)

    async def _set_night_notice(self, update, context, chat_id: int, *, mode: str) -> None:
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

    async def _start_night_input(self, update, context, chat_id: int, *, option: str, state_enum) -> None:
        valid = {"start", "end", "warn_text", "whitelist", "open_phrase", "close_phrase"}
        if option not in valid:
            await answer_callback_query_safely(update, "未识别的夜间管控输入项，请返回后重试", show_alert=True)
            return
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_enum.night_mode_text_input.value,
            payload={"target_chat_id": chat_id, "field": option},
        )
        if option in {"start", "end"}:
            await self._show_night_time_prompt(update, chat_id, option=option)
            return
        prompt_map = {
            "warn_text": "👉 请输入提示文案：",
            "whitelist": "👉 请输入白名单用户ID（用空格/逗号分隔，或输入“清空”）：",
            "open_phrase": "👉 请输入开群词：",
            "close_phrase": "👉 请输入关群词：",
        }
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:night:{chat_id}")]])
        await self.message_helper.safe_edit(update, prompt_map[option], reply_markup=markup)

    async def _show_night_time_prompt(self, update, chat_id: int, *, option: str) -> None:
        is_start = option == "start"
        sample_text = next_top_of_hour_hhmm(hours_offset=0 if is_start else 8)
        title = "🌙 夜间管控 | 编辑开始时间" if is_start else "🌙 夜间管控 | 编辑结束时间"
        hint = "👉 请输入管控开始时间（格式 HH:MM）：" if is_start else "👉 请输入管控结束时间（格式 HH:MM）："
        prompt = build_hhmm_prompt_text(title=title, sample_time_text=sample_text, input_hint=hint)
        markup = build_copy_time_keyboard(f"adm:menu:night:{chat_id}", sample_text)
        await self.message_helper.safe_edit(update, prompt, parse_mode="HTML", reply_markup=markup)
