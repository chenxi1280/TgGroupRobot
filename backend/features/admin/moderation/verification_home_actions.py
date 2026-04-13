from __future__ import annotations

from backend.features.admin.support import *


class VerificationHomeActionsMixin:
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
            await self._handle_join_spam_guard_action(update, context, chat_id, action, key, db)
            return
        if section == "self_review":
            await self._handle_join_self_review_action(update, context, chat_id, action, key, db)
            return
        if section == "burst":
            await self._handle_join_burst_guard_action(update, context, chat_id, action, key, db)
            return

        await self._show_verification_menu(update, context, chat_id)

    async def _handle_join_spam_guard_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        action: str,
        key: str,
        db: Database,
    ) -> None:
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

    async def _handle_join_self_review_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        action: str,
        key: str,
        db: Database,
    ) -> None:
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

    async def _handle_join_burst_guard_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        action: str,
        key: str,
        db: Database,
    ) -> None:
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
