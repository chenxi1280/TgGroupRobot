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
        db: Database = context.application.bot_data["db"]

        if op == "toggle":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if arg == "buttons":
                    settings.force_subscribe_custom_buttons_enabled = not bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
                else:
                    settings.force_subscribe_enabled = not bool(getattr(settings, "force_subscribe_enabled", False))
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "input":
            state_map = {
                "channel1": ConversationStateType.force_subscribe_channel_1_input.value,
                "channel2": ConversationStateType.force_subscribe_channel_2_input.value,
                "text": ConversationStateType.force_subscribe_text_input.value,
                "cover": ConversationStateType.force_subscribe_cover_input.value,
                "buttons": ConversationStateType.force_subscribe_buttons_input.value,
            }
            state_type = state_map.get(arg)
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
            prompt = {
                "channel1": "👉 请回复需要绑定的频道1（频道id、用户名或链接）：",
                "channel2": "👉 请回复需要绑定的频道2（频道id、用户名或链接）：",
                "text": "👉 现在输入新的文案内容：",
                "cover": "👉 请发送图片或视频文件；发送“清空”可移除封面。",
                "buttons": (
                    "👉 请输入按钮配置。\n"
                    "支持两种格式：\n"
                    "1) JSON：[[{\"text\":\"加入频道\",\"url\":\"https://t.me/example\"}]]\n"
                    "2) 文本行：每行一个按钮，格式“按钮文案|https://t.me/example”\n"
                    "发送“清空”可移除按钮。"
                ),
            }[arg]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:forcesub:{chat_id}")]]),
            )
            return

        if op == "preview":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                await session.commit()
            text = "👀 强制关注 | 预览效果\n\n这是用户未关注频道/群组时会收到的提示样式预览。"
            reply_markup = await _build_force_subscribe_preview_markup_async(settings, chat_id, context)
            await self.message_helper.safe_edit(update, text, reply_markup=reply_markup)
            return

        if op in {"delete_after", "cycle_delete_after"}:
            seconds = callback_data.get_int_optional(4)
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
                if seconds is None:
                    await session.commit()
                    await self.message_helper.safe_edit(
                        update,
                        "🕘 强制关注 | 删除提示消息\n\n请选择提示消息发送后多久自动删除。",
                        reply_markup=_build_force_subscribe_delete_after_keyboard(chat_id, current),
                    )
                    return
                if seconds not in FORCE_SUBSCRIBE_DELETE_AFTER_VALUES:
                    await answer_callback_query_safely(update, "请选择列表中的时间", show_alert=True)
                    return
                next_seconds = seconds
                settings.force_subscribe_delete_warn_after_seconds = next_seconds
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "cycle_check_mode":
            options = ["all", "any"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = getattr(settings, "force_subscribe_check_mode", "all")
                next_mode = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
                settings.force_subscribe_check_mode = next_mode
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "cycle_action":
            options = [
                ForceSubscribeAction.delete_and_warn.value,
                ForceSubscribeAction.delete_only.value,
                ForceSubscribeAction.warn_only.value,
                ForceSubscribeAction.mute.value,
            ]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = getattr(
                    settings,
                    "force_subscribe_not_subscribed_action",
                    ForceSubscribeAction.delete_and_warn.value,
                )
                next_action = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
                settings.force_subscribe_not_subscribed_action = next_action
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

        if op == "clear_cover":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.force_subscribe_cover_media_type = None
                settings.force_subscribe_cover_file_id = None
                await session.commit()
            await self._show_force_subscribe_menu(update, context, chat_id)
            return

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
        db: Database = context.application.bot_data["db"]

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
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = bool(getattr(settings, field, False))
                setattr(settings, field, not current)
                await session.commit()
            await self._show_new_member_limit_menu(update, context, chat_id)
            return

        if op == "input":
            if arg not in {"window", "warn_text"}:
                await answer_callback_query_safely(update, "未识别的新成员限制输入项，请返回后重试", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type=ConversationStateType.new_member_limit_text_input.value,
                payload={"target_chat_id": chat_id, "field": arg},
            )
            if arg == "window":
                await self.message_helper.safe_edit(
                    update,
                    build_numeric_duration_prompt_text(
                        title="🆕 新成员限制 | 限制时长",
                        unit_label="分钟",
                        sample_value_text="60",
                        input_hint="👉 请输入限制时长（分钟）：",
                    ),
                    parse_mode="HTML",
                    reply_markup=build_copy_options_keyboard(
                        f"adm:menu:newmem:{chat_id}",
                        [("📋 复制 60分钟", "60"), ("📋 复制 120分钟", "120")],
                    ),
                )
                return
            prompt = "👉 请输入提示文案："
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:newmem:{chat_id}")]]),
            )
            return

        if op == "cycle" and arg == "warn_delete":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "new_member_limit_warn_delete_after_seconds", 60) or 60)
                next_seconds = _cycle_config_value(current, NEW_MEMBER_WARN_DELETE_VALUES)
                settings.new_member_limit_warn_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_new_member_limit_menu(update, context, chat_id)
            return

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
        db: Database = context.application.bot_data["db"]

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
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = bool(getattr(settings, field, False))
                setattr(settings, field, not current)
                await session.commit()
            await self._show_night_mode_menu(update, context, chat_id)
            return

        if op == "notice":
            from backend.platform.db.schema.models.enums import GroupLockDeleteNoticeMode

            mode = callback_data.get(4)
            if mode not in {GroupLockDeleteNoticeMode.delete.value, GroupLockDeleteNoticeMode.keep.value}:
                await answer_callback_query_safely(update, "无效通知策略", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.group_lock_delete_notice_mode = mode
                await session.commit()
            await self._show_night_mode_menu(update, context, chat_id)
            return

        if op == "input":
            if arg not in {"start", "end", "warn_text", "whitelist", "open_phrase", "close_phrase"}:
                await answer_callback_query_safely(update, "未识别的夜间管控输入项，请返回后重试", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type=ConversationStateType.night_mode_text_input.value,
                payload={"target_chat_id": chat_id, "field": arg},
            )
            prompt_map = {
                "warn_text": "👉 请输入提示文案：",
                "whitelist": "👉 请输入白名单用户ID（用空格/逗号分隔，或输入“清空”）：",
                "open_phrase": "👉 请输入开群词：",
                "close_phrase": "👉 请输入关群词：",
            }
            if arg in {"start", "end"}:
                sample_text = next_top_of_hour_hhmm(hours_offset=0 if arg == "start" else 8)
                title = "🌙 夜间管控 | 编辑开始时间" if arg == "start" else "🌙 夜间管控 | 编辑结束时间"
                hint = "👉 请输入管控开始时间（格式 HH:MM）： " if arg == "start" else "👉 请输入管控结束时间（格式 HH:MM）： "
                await self.message_helper.safe_edit(
                    update,
                    build_hhmm_prompt_text(
                        title=title,
                        sample_time_text=sample_text,
                        input_hint=hint.strip(),
                    ),
                    parse_mode="HTML",
                    reply_markup=build_copy_time_keyboard(f"adm:menu:night:{chat_id}", sample_text),
                )
                return
            await self.message_helper.safe_edit(
                update,
                prompt_map[arg],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:night:{chat_id}")]]),
            )
            return

        if op == "cycle" and arg == "warn_delete":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                current = int(getattr(settings, "night_mode_warn_delete_after_seconds", 60) or 60)
                next_seconds = _cycle_config_value(current, NEW_MEMBER_WARN_DELETE_VALUES)
                settings.night_mode_warn_delete_after_seconds = next_seconds
                await session.commit()
            await self._show_night_mode_menu(update, context, chat_id)
            return
