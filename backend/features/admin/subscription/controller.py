from __future__ import annotations

from backend.features.admin.support import *


class SubscriptionAdminControllerMixin:
    async def _handle_renewal(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        """处理续费入口操作"""
        sub_action = callback_data.get(2) if callback_data.length() >= 3 else "page"
        if sub_action == "input":
            from backend.features.subscription.renewal_handler import start_renewal_card_input

            await start_renewal_card_input(update, context, chat_id)
            return

        await self._show_renewal_menu(update, context, chat_id)

    async def _inspect_bot_admin_health(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> str:
        """检查机器人在群内的关键管理员权限。"""
        try:
            me = await context.bot.get_me()
            member = await context.bot.get_chat_member(chat_id, me.id)
        except Exception as exc:
            log.warning("subscription_bot_admin_health_check_failed", chat_id=chat_id, error=str(exc))
            return "⚪ 权限检查：暂未获取到机器人权限，请确认机器人已在群内并具备管理员权限"

        status = getattr(member, "status", "")
        if status not in {"administrator", "creator"}:
            return "⚠️ 权限检查：机器人当前不是管理员，验证、删消息、禁言等能力可能无法生效"

        is_owner = status == "creator"
        rights = [
            ("删消息", is_owner or bool(getattr(member, "can_delete_messages", False))),
            ("禁言", is_owner or bool(getattr(member, "can_restrict_members", False))),
            ("邀请", is_owner or bool(getattr(member, "can_invite_users", False))),
            ("置顶", is_owner or bool(getattr(member, "can_pin_messages", False))),
        ]
        rights_text = " / ".join(f"{label}{'✅' if enabled else '❌'}" for label, enabled in rights)
        return f"✅ 权限检查：管理员权限正常（{rights_text}）"

    async def _show_health_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示群组健康检查页。"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            tasks = await ScheduledMessageService.list_tasks(session, chat_id, limit=200)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        permission_summary = await self._inspect_bot_admin_health(context, chat_id)

        auto_delete_flags = [
            bool(getattr(settings, "auto_delete_join", False)),
            bool(getattr(settings, "auto_delete_left", False)),
            bool(getattr(settings, "auto_delete_pinned", False)),
            bool(getattr(settings, "auto_delete_avatar", False)),
            bool(getattr(settings, "auto_delete_title", False)),
            bool(getattr(settings, "auto_delete_anonymous", False)),
        ]
        auto_delete_count = sum(auto_delete_flags)
        enabled_tasks = sum(1 for task in tasks if bool(getattr(task, "enabled", False)))
        night_control_enabled = bool(
            getattr(settings, "night_mode_enabled", False)
            or getattr(settings, "group_lock_phrase_enabled", False)
            or getattr(settings, "group_lock_schedule_enabled", False)
        )
        new_member_limit_enabled = bool(getattr(settings, "new_member_limit_enabled", False))
        new_member_limit_window = int(getattr(settings, "new_member_limit_window_seconds", 3600) or 3600)
        from backend.features.moderation.services.garbage_guard_rules import any_garbage_rule_enabled

        garbage_guard_enabled = any_garbage_rule_enabled(settings)

        lines = [
            f"🩺 [{chat_title}] 群组健康检查",
            "",
            permission_summary,
            "",
            "关键功能",
            f"• 新人验证：{'✅ 开启' if settings.verification_enabled else '❌ 关闭'}（{settings.verification_mode} / {settings.verification_timeout_seconds}秒）",
            f"• 新成员限制：{'✅ 开启' if new_member_limit_enabled else '❌ 关闭'}（{_format_duration_label(new_member_limit_window)}）",
            f"• 强制关注：{'✅ 开启' if getattr(settings, 'force_subscribe_enabled', False) else '❌ 关闭'}",
            f"• 垃圾防护：{'✅ 开启' if garbage_guard_enabled else '❌ 关闭'}",
            f"• 夜间管控：{'✅ 开启' if night_control_enabled else '❌ 关闭'}",
            f"• 自动删除：{auto_delete_count}/6 项",
            f"• 定时消息：{len(tasks)} 条（启用 {enabled_tasks} 条）",
            "",
            "风险提示",
        ]

        warnings: list[str] = []
        if getattr(settings, "force_subscribe_enabled", False):
            ch1 = getattr(settings, "force_subscribe_bound_channel_1", None)
            ch2 = getattr(settings, "force_subscribe_bound_channel_2", None)
            if not ch1 and not ch2:
                warnings.append("⚠️ 强制关注已开启但尚未绑定频道/群组")
        if getattr(settings, "group_lock_schedule_enabled", False):
            open_time = getattr(settings, "night_mode_end_time", None) or getattr(settings, "group_lock_open_time", None)
            close_time = getattr(settings, "night_mode_start_time", None) or getattr(settings, "group_lock_close_time", None)
            if not open_time or not close_time:
                warnings.append("⚠️ 夜间全员禁言已开启但管控开始/结束时间未完整配置")
        if (
            not settings.verification_enabled
            and not garbage_guard_enabled
            and not new_member_limit_enabled
        ):
            warnings.append("⚠️ 当前验证、垃圾防护均关闭，新成员保护较弱")
        if getattr(settings, "force_subscribe_enabled", False) and not settings.verification_enabled:
            warnings.append("ℹ️ 当前会先检查关注状态，建议同时开启新人验证以减少误伤")

        if warnings:
            lines.extend(warnings)
        else:
            lines.append("✅ 未发现明显配置冲突")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛡️ 新人验证", callback_data=f"adm:menu:verification:{chat_id}"),
                InlineKeyboardButton("☂️ 垃圾防护", callback_data=f"adm:menu:antispam:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🧑‍🍼 新成员限制", callback_data=f"adm:menu:newmem:{chat_id}"),
            ],
            [
                InlineKeyboardButton("📣 强制关注", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton("🌙 夜间管控", callback_data=f"adm:menu:night:{chat_id}"),
                InlineKeyboardButton("⏰ 定时消息", callback_data=f"sm:list:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🧹 自动删除", callback_data=f"adm:menu:autodel:{chat_id}"),
                InlineKeyboardButton("⚙️ 控制权限", callback_data=f"adm:menu:control:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])

        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_renewal_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示续费入口"""
        from backend.features.subscription.renewal_handler import show_renewal_menu

        await show_renewal_menu(update, context, chat_id)
