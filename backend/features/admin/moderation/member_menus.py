from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.ui.message_config_panel import (
    PanelField,
    action_button,
    button_count,
    button_status,
    format_panel,
    mark_configured,
    media_status,
    summarize_text,
)


class ModerationMemberMenusMixin:
    async def _show_force_subscribe_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.platform.db.schema.models.enums import ForceSubscribeAction

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled = bool(getattr(settings, "force_subscribe_enabled", False))
        ch1 = getattr(settings, "force_subscribe_bound_channel_1", None) or "未绑定"
        ch2 = getattr(settings, "force_subscribe_bound_channel_2", None) or "未绑定"
        delete_after = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
        default_guide_text = "{member}，您需要关注我们的频道才能发言。"
        guide_text = getattr(settings, "force_subscribe_guide_text", "") or default_guide_text
        cover_set = bool(getattr(settings, "force_subscribe_cover_file_id", None))
        custom_buttons = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
        buttons = getattr(settings, "force_subscribe_buttons", None) or []
        buttons_configured = custom_buttons and button_count(buttons) > 0
        button_summary = "跟随频道按钮" if not custom_buttons else button_status(buttons)
        check_mode = getattr(settings, "force_subscribe_check_mode", "all")
        check_mode_label = "✅ 全部频道都订阅" if check_mode == "all" else "🟡 任一频道已订阅"
        action = getattr(
            settings,
            "force_subscribe_not_subscribed_action",
            ForceSubscribeAction.delete_and_warn.value,
        )
        action_label = {
            ForceSubscribeAction.delete_and_warn.value: "删除消息并提示订阅",
            ForceSubscribeAction.delete_only.value: "仅删除消息",
            ForceSubscribeAction.warn_only.value: "仅提示订阅",
            ForceSubscribeAction.mute.value: "禁言并提示订阅",
        }.get(action, "删除消息并提示订阅")
        guide_configured = bool(str(getattr(settings, "force_subscribe_guide_text", "") or "").strip())
        text = format_panel(
            "📣 强制订阅频道",
            [
                PanelField("📡", "绑定频道1", ch1),
                PanelField("📡", "绑定频道2", ch2),
                PanelField(
                    "🏞️",
                    "封面设置",
                    media_status(
                        has_media=cover_set,
                        media_type=getattr(settings, "force_subscribe_cover_media_type", None),
                    ),
                ),
                PanelField("📄", "提示文案", summarize_text(guide_text, limit=180)),
                PanelField("⭕", "设置按钮", button_summary),
            ],
            footer=[
                f"⚙️ 状态: {'✅ 启动' if enabled else '❌ 关闭'}",
                f"🎯 订阅判定: {check_mode_label}",
                f"🚫 没订阅时处理: {action_label}",
                f"🧩 按钮来源: {'自定义按钮' if custom_buttons else '跟随频道按钮'}",
                f"🕘 删除提示消息: {delete_after}秒后删除",
                "🏖️ 预览: 发送到当前私聊",
            ],
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态:", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:fs:{chat_id}:toggle:enabled"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道1：", callback_data=f"adm:fs:{chat_id}:input:channel1"),
                InlineKeyboardButton(ch1[:16], callback_data=f"adm:fs:{chat_id}:input:channel1"),
            ],
            [
                InlineKeyboardButton("⚙️ 绑定频道2：", callback_data=f"adm:fs:{chat_id}:input:channel2"),
                InlineKeyboardButton(ch2[:16], callback_data=f"adm:fs:{chat_id}:input:channel2"),
            ],
            [
                action_button("设置封面", f"adm:fs:{chat_id}:input:cover", configured=cover_set),
                action_button("设置文案", f"adm:fs:{chat_id}:input:text", configured=guide_configured),
            ],
            [
                action_button("设置按钮", f"adm:fs:{chat_id}:input:buttons", configured=buttons_configured),
                InlineKeyboardButton("👀 预览效果", callback_data=f"adm:fs:{chat_id}:preview"),
            ],
            [
                InlineKeyboardButton("⚙️ 订阅判定：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(check_mode_label, callback_data=f"adm:fs:{chat_id}:cycle_check_mode"),
            ],
            [
                InlineKeyboardButton("⚙️ 没订阅时处理：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(action_label, callback_data=f"adm:fs:{chat_id}:cycle_action"),
            ],
            [
                InlineKeyboardButton("⚙️ 删除提示消息：", callback_data=f"adm:menu:forcesub:{chat_id}"),
                InlineKeyboardButton(
                    mark_configured(f"{delete_after}秒后删除", delete_after != 60),
                    callback_data=f"adm:fs:{chat_id}:cycle_delete_after",
                ),
            ],
            [InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:fs:{chat_id}:clear_cover")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_new_member_limit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled = bool(getattr(settings, "new_member_limit_enabled", False))
        window_seconds = int(getattr(settings, "new_member_limit_window_seconds", 3600) or 3600)
        block_media = bool(getattr(settings, "new_member_limit_block_media", True))
        block_links = bool(getattr(settings, "new_member_limit_block_links", True))
        text_only = bool(getattr(settings, "new_member_limit_text_only", False))
        delete_message = bool(getattr(settings, "new_member_limit_delete_message", True))
        warn_enabled = bool(getattr(settings, "new_member_limit_warn_enabled", True))
        warn_text = getattr(settings, "new_member_limit_warn_text", "") or "新成员需等待 {duration} 才可发送媒体/链接。"
        warn_delete = int(getattr(settings, "new_member_limit_warn_delete_after_seconds", 60) or 60)

        duration_label = _format_duration_label(window_seconds)
        text = (
            "🧑‍🍼 新成员限制\n\n"
            "用于控制新成员在入群后的可发言范围，避免新号刷广告。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"限制时长: {duration_label}\n"
            f"限制媒体: {'✅ 开启' if block_media else '❌ 关闭'}\n"
            f"限制链接: {'✅ 开启' if block_links else '❌ 关闭'}\n"
            f"仅纯文本: {'✅ 开启' if text_only else '❌ 关闭'}\n"
            f"删除触发消息: {'✅ 开启' if delete_message else '❌ 关闭'}\n"
            f"提示消息: {'✅ 开启' if warn_enabled else '❌ 关闭'}\n"
            f"提示删除: {warn_delete}秒后删除\n\n"
            f"当前提示文案:\n{warn_text}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:menu:newmem:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:nml:{chat_id}:toggle:enabled"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:nml:{chat_id}:toggle:enabled"),
            ],
            [InlineKeyboardButton(f"⏱ 限制时长（{duration_label}）", callback_data=f"adm:nml:{chat_id}:input:window")],
            [
                InlineKeyboardButton("🖼️ 媒体", callback_data=f"adm:nml:{chat_id}:toggle:block_media"),
                InlineKeyboardButton("✅ 开启" if block_media else "关闭", callback_data=f"adm:nml:{chat_id}:toggle:block_media"),
                InlineKeyboardButton("🔗 链接", callback_data=f"adm:nml:{chat_id}:toggle:block_links"),
                InlineKeyboardButton("✅ 开启" if block_links else "关闭", callback_data=f"adm:nml:{chat_id}:toggle:block_links"),
            ],
            [
                InlineKeyboardButton("📝 仅纯文本", callback_data=f"adm:nml:{chat_id}:toggle:text_only"),
                InlineKeyboardButton("✅ 开启" if text_only else "关闭", callback_data=f"adm:nml:{chat_id}:toggle:text_only"),
            ],
            [
                InlineKeyboardButton("🗑 删除触发消息", callback_data=f"adm:nml:{chat_id}:toggle:delete_message"),
                InlineKeyboardButton("✅ 开启" if delete_message else "关闭", callback_data=f"adm:nml:{chat_id}:toggle:delete_message"),
            ],
            [
                InlineKeyboardButton("💬 提示消息", callback_data=f"adm:nml:{chat_id}:toggle:warn_enabled"),
                InlineKeyboardButton("✅ 开启" if warn_enabled else "关闭", callback_data=f"adm:nml:{chat_id}:toggle:warn_enabled"),
            ],
            [
                InlineKeyboardButton("✏️ 提示文案", callback_data=f"adm:nml:{chat_id}:input:warn_text"),
                InlineKeyboardButton(f"🕒 删除提示（{warn_delete}秒）", callback_data=f"adm:nml:{chat_id}:cycle:warn_delete"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_night_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled = bool(getattr(settings, "night_mode_enabled", False))
        start_time = getattr(settings, "night_mode_start_time", None) or "未设置"
        end_time = getattr(settings, "night_mode_end_time", None) or "未设置"
        exempt_admin = bool(getattr(settings, "night_mode_exempt_admin", True))
        whitelist = getattr(settings, "night_mode_whitelist_user_ids", None) or []
        delete_message = bool(getattr(settings, "night_mode_delete_message", True))
        warn_enabled = bool(getattr(settings, "night_mode_warn_enabled", True))
        warn_text = getattr(settings, "night_mode_warn_text", "") or "🌙 夜间模式生效中，请稍后再试。"
        warn_delete = int(getattr(settings, "night_mode_warn_delete_after_seconds", 60) or 60)

        whitelist_summary = f"{len(whitelist)} 人" if whitelist else "未配置"
        text = (
            "🌙 夜间模式\n\n"
            "在指定时间段内限制发言，用于夜间防刷屏与控场。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"开始时间: {start_time}\n"
            f"结束时间: {end_time}\n"
            f"管理员豁免: {'✅ 开启' if exempt_admin else '❌ 关闭'}\n"
            f"白名单: {whitelist_summary}\n"
            f"删除触发消息: {'✅ 开启' if delete_message else '❌ 关闭'}\n"
            f"提示消息: {'✅ 开启' if warn_enabled else '❌ 关闭'}\n"
            f"提示删除: {warn_delete}秒后删除\n\n"
            f"当前提示文案:\n{warn_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:menu:night:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:night:{chat_id}:toggle:enabled"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:night:{chat_id}:toggle:enabled"),
            ],
            [
                InlineKeyboardButton(f"⏰ 开始时间（{start_time}）", callback_data=f"adm:night:{chat_id}:input:start"),
                InlineKeyboardButton(f"⏰ 结束时间（{end_time}）", callback_data=f"adm:night:{chat_id}:input:end"),
            ],
            [
                InlineKeyboardButton("🛡️ 管理员豁免", callback_data=f"adm:night:{chat_id}:toggle:exempt_admin"),
                InlineKeyboardButton("✅ 开启" if exempt_admin else "关闭", callback_data=f"adm:night:{chat_id}:toggle:exempt_admin"),
            ],
            [
                InlineKeyboardButton(f"👥 白名单（{whitelist_summary}）", callback_data=f"adm:night:{chat_id}:input:whitelist"),
            ],
            [
                InlineKeyboardButton("🗑 删除触发消息", callback_data=f"adm:night:{chat_id}:toggle:delete_message"),
                InlineKeyboardButton("✅ 开启" if delete_message else "关闭", callback_data=f"adm:night:{chat_id}:toggle:delete_message"),
            ],
            [
                InlineKeyboardButton("💬 提示消息", callback_data=f"adm:night:{chat_id}:toggle:warn_enabled"),
                InlineKeyboardButton("✅ 开启" if warn_enabled else "关闭", callback_data=f"adm:night:{chat_id}:toggle:warn_enabled"),
            ],
            [
                InlineKeyboardButton("✏️ 提示文案", callback_data=f"adm:night:{chat_id}:input:warn_text"),
                InlineKeyboardButton(f"🕒 删除提示（{warn_delete}秒）", callback_data=f"adm:night:{chat_id}:cycle:warn_delete"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
