from __future__ import annotations

from backend.features.admin.support import *


class VerificationConfigStartMixin:
    async def _handle_verification_config_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, callback_data: CallbackParser | None = None,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.platform.state.state_service import clear_user_state, set_user_state

        if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
            return
        q = update.callback_query

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
                if state_chat_id != user.id:
                    from backend.platform.state.state_service import clear_private_input_state

                    await clear_private_input_state(session, user.id)
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
        text += "验证方式:简单接受条约\n"
        text += "超时时间:180\n"
        text += "超时处理:禁言\n"
        text += "禁言时长:86400\n"
        text += "直接禁言时长:0\n"
        text += "限制发言:是\n"
        text += "```\n\n"
        text += "📋 配置说明：\n"
        text += "• 状态: 开启/关闭\n"
        text += "• 验证方式: 简单接受条约/简单加减法/直接禁言新人\n"
        text += "• 超时时间: 秒数（如 180=3分钟，直接禁言新人不生效）\n"
        text += "• 超时处理: 无/禁言/踢出\n"
        text += "• 禁言时长: 秒数（默认 86400=1天）\n"
        text += "• 直接禁言时长: 秒数，0=永久（仅直接禁言新人生效）\n"
        text += "• 限制发言: 是/否（验证期间是否限制发送消息）"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ 取消配置", callback_data=f"verification:cancel:{target_chat_id}")]
        ])

        try:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception as exc:
            log.warning("verification_config_markdown_edit_failed", target_chat_id=target_chat_id, user_id=user.id, error=str(exc))
            await q.edit_message_text(text.replace("```", ""), reply_markup=keyboard)
