from __future__ import annotations

from backend.shared.callback_parser import CallbackData

from backend.features.admin.support import *
from backend.shared.services.command_config_service import command_config_revision


class ModerationConfigActionsMixin:
    async def _require_command_config_key(self, update, command_key) -> bool:
        if command_key:
            return True
        await answer_callback_query_safely(
            update, "未识别的命令项，请返回后重试", show_alert=True
        )
        return False

    async def _toggle_command_config_entry(
        self, update, context, *, db, chat_id: int, command_key: str, enabled: bool, revision: str | None
    ) -> None:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.refresh(settings, with_for_update=True)
            entry = get_command_config(settings)["commands"].get(command_key)
            if revision != command_config_revision(settings) and (entry or {}).get("enabled", True) != enabled:
                await answer_callback_query_safely(update, "配置已更新，请刷新后操作；未覆盖他人修改。", show_alert=True)
                return
            if entry is None:
                await session.commit()
                await answer_callback_query_safely(
                    update, "未识别的命令项，请返回后重试", show_alert=True
                )
                return
            set_command_enabled(
                settings, command_key, enabled
            )
            await session.commit()
        await self._show_command_config_detail(
            update, context, chat_id, command_key=command_key
        )

    async def _start_command_alias_input(
        self, update, context, *, enum, chat_id: int, command_key: str
    ) -> None:
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            base_alias = get_command_config(settings)["commands"][command_key].get("alias")
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=enum.command_config_alias_input.value,
            payload={"target_chat_id": chat_id, "command_key": command_key, "base_alias": base_alias},
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
        *, callback_data: CallbackData,
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
        *, callback_data: CallbackData,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        op = callback_data.get(3)
        command_key = callback_data.get(4)
        db: Database = context.application.bot_data["db"]

        if op == "toggle_enabled":
            await self._show_command_config_menu(update, context, chat_id)
            return

        if op in {"enable_config", "disable_config"}:
            await _set_command_config_enabled(self, update, context, db=db, chat_id=chat_id, op=op, callback_data=callback_data)
            return
        if op == "list":
            await self._show_command_config_menu(update, context, chat_id, page=callback_data.get_int_optional(4) or 0)
            return

        if not await self._require_command_config_key(update, command_key):
            return
        if op in {"detail", "toggle"}:
            await self._show_command_config_detail(update, context, chat_id, command_key=command_key)
            return


        if op in {"enable", "disable"}:
            await self._toggle_command_config_entry(
                update, context, db=db, chat_id=chat_id, command_key=command_key, enabled=op == "enable", revision=callback_data.get(5)
            )
            return

        if op == "alias":
            await self._start_command_alias_input(
                update, context, enum=ConversationStateType,
                chat_id=chat_id, command_key=command_key,
            )
            return

        if op == "clear_alias":
            await _clear_command_alias(self, update, context, db=db, chat_id=chat_id, command_key=command_key, callback_data=callback_data)


async def _set_command_config_enabled(self, update, context, *, db, chat_id, op, callback_data):
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.refresh(settings, with_for_update=True)
        desired = op == "enable_config"
        if callback_data.get(4) != command_config_revision(settings) and settings.command_config_enabled != desired:
            await answer_callback_query_safely(update, "配置已更新，请刷新后操作。", show_alert=True)
            return
        settings.command_config_enabled = desired
        await session.commit()
    await self._show_command_config_menu(update, context, chat_id)
    return


async def _clear_command_alias(self, update, context, *, db, chat_id, command_key, callback_data):
    if not await self._require_command_config_key(update, command_key):
        return
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.refresh(settings, with_for_update=True)
        if callback_data.get(5) != command_config_revision(settings):
            await answer_callback_query_safely(update, "配置已更新，请刷新后清空。", show_alert=True)
            return
        set_command_alias(settings, command_key, None)
        await session.commit()
    await self._show_command_config_detail(update, context, chat_id, command_key=command_key)
    return
