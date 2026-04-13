from __future__ import annotations

from backend.features.admin.support import *


class ModerationConfigActionsMixin:
    async def _handle_command_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        op = callback_data.get(3)
        command_key = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle_enabled":
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.command_config_enabled = not bool(getattr(settings, "command_config_enabled", False))
                await session.commit()
            await self._show_command_config_menu(update, context, chat_id)
            return

        if op == "detail":
            if not command_key:
                await answer_callback_query_safely(update, "未识别的命令项，请返回后重试", show_alert=True)
                return
            await self._show_command_config_detail(update, context, chat_id, command_key)
            return

        if op == "toggle":
            if not command_key:
                await answer_callback_query_safely(update, "未识别的命令项，请返回后重试", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                config = get_command_config(settings)
                entry = config["commands"].get(command_key)
                if entry is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "未识别的命令项，请返回后重试", show_alert=True)
                    return
                next_enabled = not bool(entry.get("enabled", True))
                set_command_enabled(settings, command_key, next_enabled)
                await session.commit()
            await self._show_command_config_detail(update, context, chat_id, command_key)
            return

        if op == "alias":
            if not command_key:
                await answer_callback_query_safely(update, "未识别的命令项，请返回后重试", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.command_config_alias_input.value,
                {"target_chat_id": chat_id, "command_key": command_key},
            )
            await self.message_helper.safe_edit(
                update,
                "👉 请输入新的别名（无需 /），或发送“清空”移除别名：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:gcmd:{chat_id}:detail:{command_key}")]]),
            )
            return

        if op == "clear_alias":
            if not command_key:
                await answer_callback_query_safely(update, "未识别的命令项，请返回后重试", show_alert=True)
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                set_command_alias(settings, command_key, None)
                await session.commit()
            await self._show_command_config_detail(update, context, chat_id, command_key)
            return
