from __future__ import annotations

from backend.features.admin.support import *


class ModerationConfigActionsMixin:
    async def _require_command_config_key(self, update, command_key) -> bool:
        if command_key:
            return True
        await answer_callback_query_safely(
            update, "未识别的命令项，请返回后重试", show_alert=True
        )
        return False

    async def _toggle_command_config_entry(
        self, update, context, *, db, chat_id: int, command_key: str
    ) -> None:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            entry = get_command_config(settings)["commands"].get(command_key)
            if entry is None:
                await session.commit()
                await answer_callback_query_safely(
                    update, "未识别的命令项，请返回后重试", show_alert=True
                )
                return
            set_command_enabled(
                settings, command_key, not bool(entry.get("enabled", True))
            )
            await session.commit()
        await self._show_command_config_detail(
            update, context, chat_id, command_key=command_key
        )

    async def _start_command_alias_input(
        self, update, context, *, enum, chat_id: int, command_key: str
    ) -> None:
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=enum.command_config_alias_input.value,
            payload={"target_chat_id": chat_id, "command_key": command_key},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                "🔙 返回", callback_data=f"adm:gcmd:{chat_id}:detail:{command_key}"
            )]]
        )
        await self.message_helper.safe_edit(
            update, "👉 请输入新的别名（无需 /），或发送“清空”移除别名：",
            reply_markup=keyboard,
        )

    async def _handle_punishment_policy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(3) or "home"
        preset = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_punishment_policy_menu(update, context, chat_id)
            return

        if action != "preset" or preset not in {"delete", "mute", "ban"}:
            await answer_callback_query_safely(update, "未识别的惩罚策略", show_alert=True)
            return

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            settings.anti_spam_action = preset
            settings.anti_flood_action = preset
            settings.moderation_action = preset
            if preset == "mute":
                settings.verification_timeout_action = "mute"
            elif preset == "ban":
                settings.verification_timeout_action = "kick"
            await session.commit()

        await self._show_punishment_policy_menu(update, context, chat_id)
        return

    async def _handle_command_config(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
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
            if not await self._require_command_config_key(update, command_key):
                return
            await self._show_command_config_detail(update, context, chat_id, command_key=command_key)
            return

        if op == "toggle":
            if not await self._require_command_config_key(update, command_key):
                return
            await self._toggle_command_config_entry(
                update, context, db=db, chat_id=chat_id, command_key=command_key
            )
            return

        if op == "alias":
            if not await self._require_command_config_key(update, command_key):
                return
            await self._start_command_alias_input(
                update, context, enum=ConversationStateType,
                chat_id=chat_id, command_key=command_key,
            )
            return

        if op == "clear_alias":
            if not await self._require_command_config_key(update, command_key):
                return
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                set_command_alias(settings, command_key, None)
                await session.commit()
            await self._show_command_config_detail(update, context, chat_id, command_key=command_key)
            return
