from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_options_keyboard, build_numeric_duration_prompt_text


class GarageAuthActionsMixin:
    async def _handle_garage_auth(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_features_service import GarageAuthService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageAuthService.update_settings(session, chat_id, garage_auth_enabled=bool(enabled))
                await session.commit()
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "badge":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_badge_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🚗 车库认证 | 认证图标\n\n👉 请输入新的认证图标：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
            )
            return
        if action == "teacher":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_teacher_list_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_teacher_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "🚗 车库认证 | 手动添加认证老师\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:teacher:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "老师参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_teacher(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_teacher_list_menu(update, context, chat_id, 0)
                return
        if action == "limit":
            sub = callback_data.get(2)
            if sub == "toggle":
                enabled = callback_data.get_int_optional(4)
                if enabled not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_enabled=bool(enabled))
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "mode":
                mode = callback_data.get(4)
                if mode not in {"none", "image", "image_text"}:
                    await answer_callback_query_safely(update, "无效模式", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_mode=mode)
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub in {"interval", "max"}:
                state = (
                    ConversationStateType.garage_limit_interval_input.value
                    if sub == "interval"
                    else ConversationStateType.garage_limit_max_count_input.value
                )
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    state,
                    {"target_chat_id": chat_id},
                )
                prompt = "🚗 车库认证 | 时间间隔\n\n👉 请输入限制时间间隔（秒）："
                if sub == "max":
                    prompt = "🚗 车库认证 | 限制条数\n\n👉 请输入限制条数："
                if sub == "interval":
                    await self.message_helper.safe_edit(
                        update,
                        build_numeric_duration_prompt_text(
                            title="🚗 车库认证 | 时间间隔",
                            unit_label="秒",
                            sample_value_text="3600",
                            input_hint="👉 请输入限制时间间隔（秒）：",
                        ),
                        parse_mode="HTML",
                        reply_markup=build_copy_options_keyboard(
                            f"grg:home:{chat_id}",
                            [("📋 复制 3600秒", "3600"), ("📋 复制 7200秒", "7200")],
                        ),
                    )
                    return
                await self.message_helper.safe_edit(
                    update,
                    prompt,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
                )
                return
        if action == "wl":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_whitelist_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_whitelist_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "📄 老师发言限制 | 添加白名单\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:wl:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "白名单参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_whitelist(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_whitelist_menu(update, context, chat_id, 0)
                return
        if action == "summary":
            sub = callback_data.get(2)
            if sub == "menu":
                await self._show_garage_summary_menu(update, context, chat_id)
                return
            if sub == "partition":
                value = callback_data.get(4)
                if value not in {"region", "price"}:
                    await answer_callback_query_safely(update, "无效分区类型", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_partition_by=value)
                    await session.commit()
                await self._show_garage_summary_menu(update, context, chat_id)
                return
            if sub == "open":
                value = callback_data.get_int_optional(4)
                if value not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_only_open_course=bool(value))
                    await session.commit()
                await self._show_garage_summary_menu(update, context, chat_id)
                return
            if sub == "gen":
                async with db.session_factory() as session:
                    summary_text = await GarageAuthService.build_teacher_summary(session, chat_id)
                    await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    summary_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 返回汇总设置", callback_data=f"grg:summary:menu:{chat_id}")],
                        [InlineKeyboardButton("返回车库认证", callback_data=f"grg:home:{chat_id}")],
                    ]),
                )
                return
        await self._show_garage_auth_menu(update, context, chat_id)
