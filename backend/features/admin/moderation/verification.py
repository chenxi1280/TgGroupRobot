from __future__ import annotations

from backend.features.admin.support import *


class ModerationVerificationMixin:
    async def _handle_verification_config_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.platform.state.state_service import clear_user_state, set_user_state

        if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
            return
        q = update.callback_query
        await q.answer()

        chat = update.effective_chat
        user = update.effective_user

        log.warning(
            "=== VERIFICATION_CONFIG_START CALLED ===",
            target_chat_id=target_chat_id,
            user_id=user.id,
            chat_type=chat.type,
        )

        try:
            db: Database = context.application.bot_data["db"]
            from backend.platform.db.schema.models.core import ConversationState, TgChat
            from sqlalchemy import delete, select

            target_chat_title = None
            async with db.session_factory() as session:
                await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title or f"群组{target_chat_id}")

                chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
                chat_result = await session.execute(chat_stmt)
                target_chat_obj = chat_result.scalar_one_or_none()
                target_chat_title = target_chat_obj.title if target_chat_obj else f"群组{target_chat_id}"

                if chat.type == "private":
                    await ensure_chat(session, chat_id=user.id, chat_type="private", title=chat.title)

                await ensure_user(
                    session,
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    language_code=user.language_code,
                )

                state_chat_id = target_chat_id
                await clear_user_state(session, chat_id=state_chat_id, user_id=user.id)
                await clear_user_state(session, chat_id=user.id, user_id=user.id)
                await session.execute(
                    delete(ConversationState).where(
                        ConversationState.user_id == user.id,
                        ConversationState.state_type == ConversationStateType.verification_config.value,
                    )
                )
                await self._set_current_chat(db, user.id, target_chat_id)
                await set_user_state(
                    session,
                    chat_id=state_chat_id,
                    user_id=user.id,
                    state_type=ConversationStateType.verification_config.value,
                    state_data={"step": "config", "target_chat_id": target_chat_id},
                )
                await session.commit()

                log.warning(
                    "=== VERIFICATION_CONFIG_STATE_SET ===",
                    state_chat_id=state_chat_id,
                    user_id=user.id,
                    state_type=ConversationStateType.verification_config.value,
                )

        except Exception as e:
            log.exception("verification_config_start_error", error=str(e))
            await q.edit_message_text(f"❌ 启动失败: {str(e)}")
            return

        text = "🤖 验证功能配置 ( /cancel 取消)\n\n"
        text += "请按以下格式发送配置：\n\n"
        text += "```\n"
        text += "状态:开启\n"
        text += "验证方式:管理员确认\n"
        text += "超时时间:180\n"
        text += "超时处理:禁言\n"
        text += "禁言时长:86400\n"
        text += "限制发言:是\n"
        text += "```\n\n"
        text += "📋 配置说明：\n"
        text += "• 状态: 开启/关闭\n"
        text += "• 验证方式: 按钮验证/数学题/验证码/管理员确认\n"
        text += "• 超时时间: 秒数（如 180=3分钟，管理员确认模式不生效）\n"
        text += "• 超时处理: 禁言/踢出\n"
        text += "• 禁言时长: 秒数（默认 86400=1天）\n"
        text += "• 限制发言: 是/否（验证期间是否限制发送消息）"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ 取消配置", callback_data=f"verification:cancel:{target_chat_id}")]
        ])

        try:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await q.edit_message_text(text.replace("```", ""), reply_markup=keyboard)

    async def _show_verification_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        log.warning(
            "=== _SHOW_VERIFICATION_MENU CALLED ===",
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        mode_label = {
            "button": "按钮验证",
            "math": "数学题",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(settings.verification_mode, settings.verification_mode)
        status_label = "✅ 开启" if settings.verification_enabled else "❌ 关闭"
        spam_label = "✅ 开启" if bool(getattr(settings, "join_spam_guard_enabled", False)) else "❌ 关闭"
        review_label = "✅ 开启" if bool(getattr(settings, "join_self_review_enabled", False)) else "❌ 关闭"
        burst_label = "✅ 开启" if bool(getattr(settings, "join_burst_enabled", False)) else "❌ 关闭"

        text = (
            f"🛡️ [{chat_title}] 进群验证\n\n"
            f"进群验证：{status_label}｜当前方式：{mode_label}\n"
            f"垃圾拦截：{spam_label}\n"
            f"进群自助审核：{review_label}\n"
            f"禁止批量进群：{burst_label}\n\n"
            "当前已接通基础验证链路与三个辅助子页配置；执行侧仍会继续向完整 join guard 流水线补齐。"
        )

        buttons = [
            [InlineKeyboardButton("🛡️ 进群验证", callback_data=f"adm:vfy_config:{chat_id}")],
            [InlineKeyboardButton("🚯 垃圾拦截", callback_data=f"adm:vfy_home:{chat_id}:spam")],
            [InlineKeyboardButton("📝 进群自助审核", callback_data=f"adm:vfy_home:{chat_id}:self_review")],
            [InlineKeyboardButton("🚪 禁止批量进群", callback_data=f"adm:vfy_home:{chat_id}:burst")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        log.info("=== CALLING SAFE_EDIT FOR VERIFICATION MENU ===")
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        log.info("=== SAFE_EDIT COMPLETED ===")

    async def _show_join_spam_guard_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        lines = [
            "🚯 进群验证 | 垃圾拦截",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_spam_guard_enabled else '❌ 关闭'}",
            f"🧪 命中阈值：{settings.join_spam_detect_rules_count} 条",
            f"💬 提示消息：{'✅ 开启' if settings.join_spam_send_invalid_msg_enabled else '❌ 关闭'}",
            f"🔇 禁言新人：{'✅ 开启' if settings.join_spam_mute_member_enabled else '❌ 关闭'}",
            f"👢 踢出新人：{'✅ 开启' if settings.join_spam_kick_member_enabled else '❌ 关闭'}",
            f"⏱️ 提示删除：{settings.join_spam_tip_delete_after_seconds} 秒",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_spam_guard_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:enabled"),
                InlineKeyboardButton(f"🧪 阈值 {settings.join_spam_detect_rules_count}", callback_data=f"adm:vfy_home:{chat_id}:spam:cycle:rules"),
            ],
            [
                InlineKeyboardButton(("💬 提示 ✅" if settings.join_spam_send_invalid_msg_enabled else "💬 提示 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:notify"),
                InlineKeyboardButton(("🔇 禁言 ✅" if settings.join_spam_mute_member_enabled else "🔇 禁言 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:mute"),
            ],
            [
                InlineKeyboardButton(("👢 踢出 ✅" if settings.join_spam_kick_member_enabled else "👢 踢出 ❌"), callback_data=f"adm:vfy_home:{chat_id}:spam:toggle:kick"),
                InlineKeyboardButton(f"⏱️ 删除 {settings.join_spam_tip_delete_after_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:spam:cycle:tip_sec"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_join_self_review_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        timeout_action_label = JOIN_SELF_REVIEW_ACTION_LABELS.get(
            settings.join_self_review_timeout_action,
            settings.join_self_review_timeout_action,
        )
        wrong_action_label = JOIN_SELF_REVIEW_ACTION_LABELS.get(
            settings.join_self_review_wrong_action,
            settings.join_self_review_wrong_action,
        )
        lines = [
            "📝 进群验证 | 自助审核",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_self_review_enabled else '❌ 关闭'}",
            f"⏱️ 超时：{settings.join_self_review_timeout_seconds} 秒",
            f"⌛ 超时策略：{timeout_action_label}",
            f"❓ 答错策略：{wrong_action_label}",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_self_review_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:self_review:toggle:enabled"),
                InlineKeyboardButton(f"⏱️ 超时 {settings.join_self_review_timeout_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:timeout"),
            ],
            [
                InlineKeyboardButton(timeout_action_label, callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:timeout_action"),
            ],
            [
                InlineKeyboardButton(wrong_action_label, callback_data=f"adm:vfy_home:{chat_id}:self_review:cycle:wrong_action"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_join_burst_guard_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        tip_mode_label = JOIN_BURST_TIP_MODE_LABELS.get(settings.join_burst_tip_mode, settings.join_burst_tip_mode)
        lines = [
            "🚪 进群验证 | 禁止批量进群",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_burst_enabled else '❌ 关闭'}",
            f"🪟 时间窗口：{settings.join_burst_window_seconds} 秒",
            f"👥 触发人数：{settings.join_burst_threshold_count} 人",
            f"🔇 禁言：{'✅ 开启' if settings.join_burst_mute_enabled else '❌ 关闭'}",
            f"👢 踢出：{'✅ 开启' if settings.join_burst_kick_enabled else '❌ 关闭'}",
            f"💬 提示策略：{tip_mode_label}",
        ]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 状态" if settings.join_burst_enabled else "❌ 状态", callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:enabled"),
                InlineKeyboardButton(f"🪟 窗口 {settings.join_burst_window_seconds}s", callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:window"),
            ],
            [
                InlineKeyboardButton(f"👥 阈值 {settings.join_burst_threshold_count}", callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:threshold"),
                InlineKeyboardButton(("🔇 禁言 ✅" if settings.join_burst_mute_enabled else "🔇 禁言 ❌"), callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:mute"),
            ],
            [
                InlineKeyboardButton(("👢 踢出 ✅" if settings.join_burst_kick_enabled else "👢 踢出 ❌"), callback_data=f"adm:vfy_home:{chat_id}:burst:toggle:kick"),
                InlineKeyboardButton(tip_mode_label, callback_data=f"adm:vfy_home:{chat_id}:burst:cycle:tip_mode"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _handle_verification_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        section = callback_data.get(3)
        action = callback_data.get(4)
        key = callback_data.get(5)
        db: Database = context.application.bot_data["db"]

        if section == "spam":
            if action in {"", "home"}:
                await self._show_join_spam_guard_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle":
                    field_map = {
                        "enabled": "join_spam_guard_enabled",
                        "notify": "join_spam_send_invalid_msg_enabled",
                        "mute": "join_spam_mute_member_enabled",
                        "kick": "join_spam_kick_member_enabled",
                    }
                    field = field_map.get(key)
                    if field:
                        setattr(settings, field, not bool(getattr(settings, field)))
                elif action == "cycle":
                    if key == "rules":
                        settings.join_spam_detect_rules_count = _cycle_config_value(
                            settings.join_spam_detect_rules_count,
                            JOIN_SPAM_RULE_VALUES,
                        )
                    elif key == "tip_sec":
                        settings.join_spam_tip_delete_after_seconds = _cycle_config_value(
                            settings.join_spam_tip_delete_after_seconds,
                            JOIN_SPAM_TIP_DELETE_VALUES,
                        )
                await session.commit()
            await self._show_join_spam_guard_menu(update, context, chat_id)
            return

        if section == "self_review":
            if action in {"", "home"}:
                await self._show_join_self_review_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle" and key == "enabled":
                    settings.join_self_review_enabled = not bool(settings.join_self_review_enabled)
                elif action == "cycle":
                    if key == "timeout":
                        settings.join_self_review_timeout_seconds = _cycle_config_value(
                            settings.join_self_review_timeout_seconds,
                            JOIN_SELF_REVIEW_TIMEOUT_VALUES,
                        )
                    elif key == "timeout_action":
                        settings.join_self_review_timeout_action = _cycle_config_value(
                            settings.join_self_review_timeout_action,
                            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
                        )
                    elif key == "wrong_action":
                        settings.join_self_review_wrong_action = _cycle_config_value(
                            settings.join_self_review_wrong_action,
                            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
                        )
                await session.commit()
            await self._show_join_self_review_menu(update, context, chat_id)
            return

        if section == "burst":
            if action in {"", "home"}:
                await self._show_join_burst_guard_menu(update, context, chat_id)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if action == "toggle":
                    field_map = {
                        "enabled": "join_burst_enabled",
                        "mute": "join_burst_mute_enabled",
                        "kick": "join_burst_kick_enabled",
                    }
                    field = field_map.get(key)
                    if field:
                        setattr(settings, field, not bool(getattr(settings, field)))
                elif action == "cycle":
                    if key == "window":
                        settings.join_burst_window_seconds = _cycle_config_value(
                            settings.join_burst_window_seconds,
                            JOIN_BURST_WINDOW_VALUES,
                        )
                    elif key == "threshold":
                        settings.join_burst_threshold_count = _cycle_config_value(
                            settings.join_burst_threshold_count,
                            JOIN_BURST_THRESHOLD_VALUES,
                        )
                    elif key == "tip_mode":
                        settings.join_burst_tip_mode = _cycle_config_value(
                            settings.join_burst_tip_mode,
                            list(JOIN_BURST_TIP_MODE_LABELS.keys()),
                        )
                await session.commit()
            await self._show_join_burst_guard_menu(update, context, chat_id)
            return

        await self._show_verification_menu(update, context, chat_id)

