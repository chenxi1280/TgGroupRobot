from __future__ import annotations

from backend.features.admin.support import *
_DURATION_LABEL_THRESHOLD_3600 = 3600
_DURATION_LABEL_THRESHOLD_60 = 60
_DURATION_LABEL_THRESHOLD_86400 = 86400



VERIFICATION_RULES = [
    ("button", "📄 简单接受条约", "用户需要点击同意按钮"),
    ("math", "🔢 简单加减法", "用户需要做一道简单算术题"),
    ("mute", "🤐 直接禁言新人", "新用户一律禁言"),
]


def _status_label(enabled: bool) -> str:
    return "✅ 启动" if enabled else "❌ 关闭"


def _duration_label(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "永久"
    if seconds < _DURATION_LABEL_THRESHOLD_60:
        return f"{seconds}秒"
    if seconds < _DURATION_LABEL_THRESHOLD_3600:
        return f"{seconds // 60}分钟"
    if seconds < _DURATION_LABEL_THRESHOLD_86400:
        return f"{seconds // 3600}小时"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}天"
    return f"{seconds}秒"


def _verification_action_label(action: str) -> str:
    return VERIFICATION_ACTION_LABELS.get(action, action or "不额外处理")


def _verification_mode_label(mode: str) -> str:
    return VERIFICATION_MODE_LABELS.get(mode, mode or "未启用")


def _media_status(settings) -> str:
    media_type = getattr(settings, "verification_cover_media_type", None)
    if not getattr(settings, "verification_cover_file_id", None):
        return "未设置"
    return "图片" if media_type == "photo" else "视频" if media_type == "video" else "已设置"


def _short_text(value: str | None, *, limit: int = 56) -> str:
    text = (value or "").strip()
    if not text:
        return "未设置"
    return text if len(text) <= limit else text[:limit] + "..."


class VerificationViewsMixin:
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
        verification_label = _verification_mode_label(settings.verification_mode) if settings.verification_enabled else "关闭"
        spam_label = "启动" if bool(getattr(settings, "join_spam_guard_enabled", False)) else "关闭"
        review_label = "启动" if bool(getattr(settings, "join_self_review_enabled", False)) else "关闭"
        burst_label = "启动" if bool(getattr(settings, "join_burst_enabled", False)) else "关闭"

        text = (
            f"🛡️ [{chat_title}] 进群验证\n\n"
            "进群验证 - 新人未通过验证则进行限制\n"
            "垃圾拦截 - 新加入的人员进行规则筛选\n\n"
            f"进群验证：{verification_label}\n"
            f"垃圾拦截：{spam_label}\n"
            f"进群自助审核：{review_label}\n"
            f"禁止批量进群：{burst_label}"
        )

        buttons = [
            [InlineKeyboardButton("🤖 进群验证", callback_data=f"adm:vfy_home:{chat_id}:rules")],
            [InlineKeyboardButton("👻 垃圾拦截", callback_data=f"adm:vfy_home:{chat_id}:spam")],
            [InlineKeyboardButton("🛡️ 进群自助审核", callback_data=f"adm:vfy_home:{chat_id}:self_review")],
            [InlineKeyboardButton("🚧 禁止批量进群", callback_data=f"adm:vfy_home:{chat_id}:burst")],
            [InlineKeyboardButton("⚠️ 超时失败任务", callback_data=f"adm:vfy_home:{chat_id}:timeouts")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        log.info("=== CALLING SAFE_EDIT FOR VERIFICATION MENU ===")
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        log.info("=== SAFE_EDIT COMPLETED ===")

    async def _show_verification_rules_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        active_mode = settings.verification_mode if settings.verification_enabled else ""
        active_label = _verification_mode_label(active_mode) if active_mode else "未启用"
        lines = [
            "🔢 进群验证",
            "",
            "简单接受条约 - 用户需要点击同意按钮",
            "简单加减法 - 用户需要做一道简单算术题",
            "直接禁言新人 - 新用户一律禁言",
            "",
            "只能启用一个验证，开启一个规则时，会自动关闭其他规则。",
            f"当前启用：{active_label}",
        ]
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{'✅' if active_mode == mode else '❌'} {label}",
                        callback_data=f"adm:vfy_home:{chat_id}:rule:{mode}",
                    )
                ]
                for mode, label, _ in VERIFICATION_RULES
            ]
            + [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_verification_rule_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, mode: str,
    ) -> None:
        if mode == "math":
            await self._show_verification_math_detail(update, context, chat_id)
            return
        if mode == "mute":
            await self._show_verification_mute_detail(update, context, chat_id)
            return
        await self._show_verification_agreement_detail(update, context, chat_id)

    async def _show_verification_agreement_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        active = bool(settings.verification_enabled) and settings.verification_mode == "button"
        text = "\n".join(
            [
                "📄 简单接受条约",
                "",
                "用户需要点击同意群规条约按钮，超时未点击或者点击不同意，都将进行惩罚。",
                "",
                f"⚙️ 状态：{_status_label(active)}",
                f"🏞️ 封面：{_media_status(settings)}",
                f"📄 条约：{_short_text(getattr(settings, 'verification_agreement_text', None))}",
                f"⏱️ 允许点击时长：{_duration_label(settings.verification_timeout_seconds)}",
                f"⛔ 超时处理：{_verification_action_label(settings.verification_timeout_action)}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 启动" if not active else "✅ 已启动", callback_data=f"adm:vfy_home:{chat_id}:rule:button:toggle"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"adm:vfy_home:{chat_id}:rule:button:disable"),
            ],
            [
                InlineKeyboardButton("🏞️ 设置封面", callback_data=f"adm:vfy_home:{chat_id}:rule:button:input:cover"),
                InlineKeyboardButton("📝 设置条约", callback_data=f"adm:vfy_home:{chat_id}:rule:button:input:text"),
            ],
            [InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:vfy_home:{chat_id}:rule:button:preview")],
            [
                InlineKeyboardButton(f"⏱️ 时长 {_duration_label(settings.verification_timeout_seconds)}", callback_data=f"adm:vfy_home:{chat_id}:rule:button:cycle:timeout"),
                InlineKeyboardButton(f"⛔ 超时 {_verification_action_label(settings.verification_timeout_action)}", callback_data=f"adm:vfy_home:{chat_id}:rule:button:cycle:timeout_action"),
            ],
            [InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:vfy_home:{chat_id}:rule:button:clear_cover")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rules")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_verification_math_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        active = bool(settings.verification_enabled) and settings.verification_mode == "math"
        text = "\n".join(
            [
                "🔢 简单加减法",
                "",
                "用户需要做一道简单算术题，超时未答或者答错将按设置处理。",
                "",
                f"⚙️ 状态：{_status_label(active)}",
                f"🏞️ 封面：{_media_status(settings)}",
                f"📝 文案：{_short_text(getattr(settings, 'verification_math_prompt_text', None))}",
                f"⏱️ 允许回答时长：{_duration_label(settings.verification_timeout_seconds)}",
                f"⛔ 超时处理：{_verification_action_label(settings.verification_timeout_action)}",
                f"❓ 答错处理：{_verification_action_label(getattr(settings, 'verification_wrong_action', 'none'))}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 启动" if not active else "✅ 已启动", callback_data=f"adm:vfy_home:{chat_id}:rule:math:toggle"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"adm:vfy_home:{chat_id}:rule:math:disable"),
            ],
            [
                InlineKeyboardButton("🏞️ 设置封面", callback_data=f"adm:vfy_home:{chat_id}:rule:math:input:cover"),
                InlineKeyboardButton("📝 设置文案", callback_data=f"adm:vfy_home:{chat_id}:rule:math:input:text"),
            ],
            [InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:vfy_home:{chat_id}:rule:math:preview")],
            [
                InlineKeyboardButton(f"⏱️ 时长 {_duration_label(settings.verification_timeout_seconds)}", callback_data=f"adm:vfy_home:{chat_id}:rule:math:cycle:timeout"),
                InlineKeyboardButton(f"⛔ 超时 {_verification_action_label(settings.verification_timeout_action)}", callback_data=f"adm:vfy_home:{chat_id}:rule:math:cycle:timeout_action"),
            ],
            [InlineKeyboardButton(f"❓ 答错 {_verification_action_label(getattr(settings, 'verification_wrong_action', 'none'))}", callback_data=f"adm:vfy_home:{chat_id}:rule:math:cycle:wrong_action")],
            [InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:vfy_home:{chat_id}:rule:math:clear_cover")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rules")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_verification_mute_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        active = bool(settings.verification_enabled) and settings.verification_mode == "mute"
        duration = int(getattr(settings, "verification_direct_mute_duration", 0) or 0)
        text = "\n".join(
            [
                "🤐 直接禁言新人",
                "",
                "新用户进群后直接禁言，直到禁言到期或者管理员解除用户禁言为止。",
                "",
                f"⚙️ 状态：{_status_label(active)}",
                f"🔇 禁言时长：{_duration_label(duration)}",
                "",
                "管理员可回复用户消息发送“解封”，或发送“解封 @用户”手动解禁。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 启动" if not active else "✅ 已启动", callback_data=f"adm:vfy_home:{chat_id}:rule:mute:toggle"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"adm:vfy_home:{chat_id}:rule:mute:disable"),
            ],
            [InlineKeyboardButton(f"🔇 时长 {_duration_label(duration)}", callback_data=f"adm:vfy_home:{chat_id}:rule:mute:cycle:duration")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:vfy_home:{chat_id}:rules")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

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
        force_sub_enabled = bool(getattr(settings, "force_subscribe_enabled", False))
        ch1 = getattr(settings, "force_subscribe_bound_channel_1", None) or "未绑定"
        ch2 = getattr(settings, "force_subscribe_bound_channel_2", None) or "未绑定"
        check_mode = getattr(settings, "force_subscribe_check_mode", "all")
        check_mode_label = "全部频道/群组" if check_mode == "all" else "任一频道/群组"
        force_action = getattr(settings, "force_subscribe_not_subscribed_action", "delete_and_warn")
        force_action_label = {
            "delete_and_warn": "删除消息并提示",
            "delete_only": "仅删除消息",
            "warn_only": "仅提示",
            "mute": "禁言并提示",
        }.get(force_action, force_action)
        lines = [
            "📝 进群验证 | 自助审核",
            "",
            f"📌 状态：{'✅ 开启' if settings.join_self_review_enabled else '❌ 关闭'}",
            f"⏱️ 超时：{settings.join_self_review_timeout_seconds} 秒",
            f"⌛ 超时策略：{timeout_action_label}",
            f"❓ 答错策略：{wrong_action_label}",
            "",
            f"📣 强制关注：{'✅ 开启' if force_sub_enabled else '❌ 关闭'}",
            f"📡 频道/群组1：{ch1}",
            f"📡 频道/群组2：{ch2}",
            f"🎯 关注判定：{check_mode_label}",
            f"🚫 未关注处理：{force_action_label}",
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
            [
                InlineKeyboardButton("📣 关注 ✅" if force_sub_enabled else "📣 关注 ❌", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_toggle:enabled"),
                InlineKeyboardButton(f"🎯 {check_mode_label}", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_cycle:check_mode"),
            ],
            [
                InlineKeyboardButton("📡 频道/群组1", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_input:channel1"),
                InlineKeyboardButton("📡 频道/群组2", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_input:channel2"),
            ],
            [
                InlineKeyboardButton(f"🚫 {force_action_label}", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_cycle:action"),
                InlineKeyboardButton("📝 提示文案", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_input:text"),
            ],
            [InlineKeyboardButton("👀 预览关注提示", callback_data=f"adm:vfy_home:{chat_id}:self_review:fs_preview")],
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
