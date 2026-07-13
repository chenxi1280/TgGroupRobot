from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.admin.module_settings import (
    build_force_subscribe_preview_markup_async as _build_force_subscribe_preview_markup_async,
)
from backend.features.admin.support_constants import (
    JOIN_BURST_THRESHOLD_VALUES,
    JOIN_BURST_TIP_MODE_LABELS,
    JOIN_BURST_WINDOW_VALUES,
    JOIN_SELF_REVIEW_ACTION_LABELS,
    JOIN_SELF_REVIEW_TIMEOUT_VALUES,
    JOIN_SPAM_RULE_VALUES,
    JOIN_SPAM_TIP_DELETE_VALUES,
    VERIFICATION_ACTION_LABELS,
    VERIFICATION_DIRECT_MUTE_DURATION_VALUES,
    VERIFICATION_TIMEOUT_VALUES,
)
from backend.features.admin.support_helpers import _cycle_config_value
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings


def _apply_verification_rule(settings, *, mode: str, action: str, key: str) -> None:
    if action == "toggle":
        settings.verification_enabled = True
        settings.verification_mode = mode
        return
    if action == "disable":
        if settings.verification_mode == mode:
            settings.verification_enabled = False
        return
    if action == "clear_cover":
        settings.verification_cover_media_type = None
        settings.verification_cover_file_id = None
        return
    if action != "cycle":
        raise ValueError(f"未识别的验证规则操作: {action}")
    _cycle_verification_rule(settings, key)


def _cycle_verification_rule(settings, key: str) -> None:
    definitions = {
        "timeout": ("verification_timeout_seconds", VERIFICATION_TIMEOUT_VALUES, None),
        "timeout_action": (
            "verification_timeout_action",
            list(VERIFICATION_ACTION_LABELS.keys()),
            None,
        ),
        "wrong_action": (
            "verification_wrong_action",
            list(VERIFICATION_ACTION_LABELS.keys()),
            "none",
        ),
        "duration": (
            "verification_direct_mute_duration",
            VERIFICATION_DIRECT_MUTE_DURATION_VALUES,
            0,
        ),
    }
    definition = definitions.get(key)
    if definition is None:
        raise ValueError(f"未识别的验证规则配置: {key}")
    field, values, default = definition
    current = getattr(settings, field, default)
    setattr(settings, field, _cycle_config_value(current, values))


def _toggle_mapped_setting(settings, key: str, field_map: dict[str, str]) -> None:
    field = field_map.get(key)
    if field is None:
        raise ValueError(f"未识别的开关配置: {key}")
    setattr(settings, field, not bool(getattr(settings, field)))


def _apply_join_spam_setting(settings, action: str, key: str) -> None:
    if action == "toggle":
        _toggle_mapped_setting(settings, key, {
            "enabled": "join_spam_guard_enabled",
            "notify": "join_spam_send_invalid_msg_enabled",
            "mute": "join_spam_mute_member_enabled",
            "kick": "join_spam_kick_member_enabled",
        })
        return
    definitions = {
        "rules": ("join_spam_detect_rules_count", JOIN_SPAM_RULE_VALUES),
        "tip_sec": ("join_spam_tip_delete_after_seconds", JOIN_SPAM_TIP_DELETE_VALUES),
    }
    if action != "cycle" or key not in definitions:
        raise ValueError(f"未识别的入群广告检测配置: {action}/{key}")
    field, values = definitions[key]
    setattr(settings, field, _cycle_config_value(getattr(settings, field), values))


def _apply_join_burst_setting(settings, action: str, key: str) -> None:
    if action == "toggle":
        _toggle_mapped_setting(settings, key, {
            "enabled": "join_burst_enabled",
            "mute": "join_burst_mute_enabled",
            "kick": "join_burst_kick_enabled",
        })
        return
    definitions = {
        "window": ("join_burst_window_seconds", JOIN_BURST_WINDOW_VALUES),
        "threshold": ("join_burst_threshold_count", JOIN_BURST_THRESHOLD_VALUES),
        "tip_mode": ("join_burst_tip_mode", list(JOIN_BURST_TIP_MODE_LABELS.keys())),
    }
    if action != "cycle" or key not in definitions:
        raise ValueError(f"未识别的突发入群配置: {action}/{key}")
    field, values = definitions[key]
    setattr(settings, field, _cycle_config_value(getattr(settings, field), values))


def _apply_self_review_setting(settings, action: str, key: str) -> None:
    if action == "toggle" and key == "enabled":
        settings.join_self_review_enabled = not bool(settings.join_self_review_enabled)
        return
    if action == "fs_toggle" and key == "enabled":
        settings.force_subscribe_enabled = not bool(getattr(settings, "force_subscribe_enabled", False))
        return
    if action == "fs_cycle":
        _cycle_force_subscribe_setting(settings, key)
        return
    if action == "cycle":
        _cycle_self_review_setting(settings, key)
        return
    raise ValueError(f"未识别的自助审核配置: {action}/{key}")


def _cycle_force_subscribe_setting(settings, key: str) -> None:
    if key == "check_mode":
        settings.force_subscribe_check_mode = _cycle_config_value(
            getattr(settings, "force_subscribe_check_mode", "all"),
            ["all", "any"],
        )
        return
    if key != "action":
        raise ValueError(f"未识别的强制关注配置: {key}")
    from backend.platform.db.schema.models.enums import ForceSubscribeAction

    actions = [
        ForceSubscribeAction.delete_and_warn.value,
        ForceSubscribeAction.delete_only.value,
        ForceSubscribeAction.warn_only.value,
        ForceSubscribeAction.mute.value,
    ]
    current = getattr(
        settings,
        "force_subscribe_not_subscribed_action",
        ForceSubscribeAction.delete_and_warn.value,
    )
    settings.force_subscribe_not_subscribed_action = _cycle_config_value(current, actions)


def _cycle_self_review_setting(settings, key: str) -> None:
    definitions = {
        "timeout": ("join_self_review_timeout_seconds", JOIN_SELF_REVIEW_TIMEOUT_VALUES),
        "timeout_action": (
            "join_self_review_timeout_action",
            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
        ),
        "wrong_action": (
            "join_self_review_wrong_action",
            list(JOIN_SELF_REVIEW_ACTION_LABELS.keys()),
        ),
    }
    definition = definitions.get(key)
    if definition is None:
        raise ValueError(f"未识别的自助审核配置: {key}")
    field, values = definition
    setattr(settings, field, _cycle_config_value(getattr(settings, field), values))


class VerificationHomeActionsMixin:
    async def _handle_verification_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        section = callback_data.get(3)
        action = callback_data.get(4)
        key = callback_data.get(5)
        value = callback_data.get(6)
        db: Database = context.application.bot_data["db"]

        if section == "rules":
            await self._show_verification_rules_menu(update, context, chat_id)
            return
        if section == "rule":
            await self._handle_verification_rule_action(update, context, chat_id, mode=action, action=key, key=value, db=db)
            return
        if section == "spam":
            await self._handle_join_spam_guard_action(update, context, chat_id, action=action, key=key, db=db)
            return
        if section == "self_review":
            await self._handle_join_self_review_action(update, context, chat_id, action=action, key=key, db=db)
            return
        if section == "burst":
            await self._handle_join_burst_guard_action(update, context, chat_id, action=action, key=key, db=db)
            return
        if section == "timeouts":
            await self._handle_verification_timeout_action(
                update,
                context,
                chat_id=chat_id,
                action=action,
                challenge_key=key,
            )
            return

        await self._show_verification_menu(update, context, chat_id)

    async def _handle_verification_rule_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, mode: str,
        action: str,
        key: str,
        db: Database,
    ) -> None:
        if mode not in {"button", "math", "mute"}:
            await answer_callback_query_safely(update, "未识别的验证规则", show_alert=True)
            return

        if action in {"", "home"}:
            await self._show_verification_rule_detail(update, context, chat_id, mode=mode)
            return

        if action == "preview":
            await self._show_verification_rule_preview(update, context, chat_id, mode=mode)
            return

        if action == "input":
            await self._start_verification_rule_input(update, context, chat_id, mode=mode, field=key)
            return

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            try:
                _apply_verification_rule(settings, mode=mode, action=action, key=key)
            except ValueError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await session.commit()

        await self._show_verification_rule_detail(update, context, chat_id, mode=mode)

    async def _start_verification_rule_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, mode: str,
        field: str,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        if field == "cover":
            state_type = ConversationStateType.verification_cover_input.value
            prompt = "👉 请发送图片或视频作为验证封面；发送“清空”可移除封面。"
        elif field == "text" and mode == "button":
            state_type = ConversationStateType.verification_agreement_text_input.value
            prompt = "👉 请输入新的群规条约文案；发送“清空”恢复默认。"
        elif field == "text" and mode == "math":
            state_type = ConversationStateType.verification_math_prompt_text_input.value
            prompt = "👉 请输入数学题验证前置文案；发送“清空”恢复默认。"
        else:
            await answer_callback_query_safely(update, "未识别的配置项", show_alert=True)
            return

        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_type,
            payload={"target_chat_id": chat_id, "return_rule": mode},
        )
        await self.message_helper.safe_edit(
            update,
            prompt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rule:{mode}")]]),
        )

    async def _show_verification_rule_preview(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, mode: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        if mode == "math":
            from backend.features.verification.verification_service import generate_math_question

            question, _ = generate_math_question()
            text = (
                f"🔢 简单加减法 | 预览\n\n"
                f"{getattr(settings, 'verification_math_prompt_text', '') or '请回答下面的简单算术题完成验证。'}\n\n"
                f"<b>{question}</b>\n\n"
                f"⏱️ {settings.verification_timeout_seconds} 秒内完成"
            )
        elif mode == "mute":
            text = (
                "🤐 直接禁言新人 | 预览\n\n"
                f"新人进群后会被禁言：{getattr(settings, 'verification_direct_mute_duration', 0) or 0} 秒（0=永久）。"
            )
        else:
            text = (
                "📄 简单接受条约 | 预览\n\n"
                f"{getattr(settings, 'verification_agreement_text', '') or '请阅读并同意本群规则后再发言。'}\n\n"
                f"⏱️ {settings.verification_timeout_seconds} 秒内点击。"
            )
            await self.message_helper.safe_edit(
                update,
                text,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ 同意", callback_data=f"adm:vfy_home:{chat_id}:rule:button"),
                        InlineKeyboardButton("❌ 不同意", callback_data=f"adm:vfy_home:{chat_id}:rule:button"),
                    ],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rule:button")],
                ]),
            )
            return

        await self.message_helper.safe_edit(
            update,
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rule:{mode}")]]),
        )

    async def _handle_join_spam_guard_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, action: str,
        key: str,
        db: Database,
    ) -> None:
        if action in {"", "home"}:
            await self._show_join_spam_guard_menu(update, context, chat_id)
            return
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            try:
                _apply_join_spam_setting(settings, action, key)
            except ValueError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await session.commit()
        await self._show_join_spam_guard_menu(update, context, chat_id)

    async def _handle_join_self_review_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, action: str,
        key: str,
        db: Database,
    ) -> None:
        if action in {"", "home"}:
            await self._show_join_self_review_menu(update, context, chat_id)
            return
        if action == "fs_preview":
            await self._show_force_subscribe_preview(update, context, chat_id, db=db)
            return
        if action == "fs_input":
            await self._start_force_subscribe_input(update, context, chat_id, key=key)
            return
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            try:
                _apply_self_review_setting(settings, action, key)
            except ValueError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await session.commit()
        await self._show_join_self_review_menu(update, context, chat_id)

    async def _show_force_subscribe_preview(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        db: Database,
    ) -> None:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()
        markup = await _build_force_subscribe_preview_markup_async(
            settings,
            chat_id,
            context,
            back_callback=f"adm:vfy_home:{chat_id}:self_review",
        )
        await self.message_helper.safe_edit(
            update,
            "👀 强制关注 | 预览效果\n\n这是用户未关注频道/群组时会收到的提示样式预览。",
            reply_markup=markup,
        )

    async def _start_force_subscribe_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        key: str,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType

        state_map = {
            "channel1": ConversationStateType.force_subscribe_channel_1_input.value,
            "channel2": ConversationStateType.force_subscribe_channel_2_input.value,
            "text": ConversationStateType.force_subscribe_text_input.value,
        }
        prompts = {
            "channel1": "👉 请回复需要绑定的频道/群组1（ID、用户名或链接）：",
            "channel2": "👉 请回复需要绑定的频道/群组2（ID、用户名或链接）：",
            "text": "👉 请输入未关注时的提示文案：",
        }
        if key not in state_map:
            await answer_callback_query_safely(update, "未识别的强制关注配置项", show_alert=True)
            return
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=state_map[key],
            payload={"target_chat_id": chat_id, "return_to": "verification_self_review"},
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:self_review")
        ]])
        await self.message_helper.safe_edit(update, prompts[key], reply_markup=keyboard)

    async def _handle_join_burst_guard_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, action: str,
        key: str,
        db: Database,
    ) -> None:
        if action in {"", "home"}:
            await self._show_join_burst_guard_menu(update, context, chat_id)
            return
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            try:
                _apply_join_burst_setting(settings, action, key)
            except ValueError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await session.commit()
        await self._show_join_burst_guard_menu(update, context, chat_id)
