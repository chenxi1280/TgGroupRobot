from __future__ import annotations

from backend.features.admin.support import *


class ModerationControlMenusMixin:
    async def _show_control_permission_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.platform.db.schema.models.enums import ControlPermissionPolicy

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        current = getattr(settings, "control_permission_policy", ControlPermissionPolicy.can_promote_members.value)
        rows = [
            ("所有管理员", ControlPermissionPolicy.all_admins.value),
            ("拥有封禁权限", ControlPermissionPolicy.can_restrict_members.value),
            ("拥有更改群组权限", ControlPermissionPolicy.can_change_info.value),
            ("拥有添加管理员权限", ControlPermissionPolicy.can_promote_members.value),
            ("仅创建者", ControlPermissionPolicy.owner_only.value),
        ]
        buttons = []
        for label, value in rows:
            prefix = "✅" if current == value else "❌"
            buttons.append([InlineKeyboardButton(f"{prefix} {label}", callback_data=f"adm:perm:{chat_id}:{value}")])
        buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])

        current_label = next((label for label, value in rows if value == current), "拥有添加管理员权限")
        text = (
            "⚙️ 控制权限\n\n"
            "你可以制定哪些管理员能够设置机器人。\n\n"
            f"当前策略：{current_label}\n\n"
            "当前统一影响以下管理能力：设置页、风控页、功能工作台。"
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_group_lock_menu(
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

        def on_label(v: bool) -> str:
            return "✅ 启动" if v else "启动"

        def off_label(v: bool) -> str:
            return "❌ 关闭" if not v else "关闭"

        delete_label = "删除" if getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete" else "不删除"
        open_time = getattr(settings, "group_lock_open_time", None) or "未设置"
        close_time = getattr(settings, "group_lock_close_time", None) or "未设置"
        open_phrase = getattr(settings, "group_lock_open_phrase", None) or "开群了"
        close_phrase = getattr(settings, "group_lock_close_phrase", None) or "关群了"
        phrase_enabled = bool(getattr(settings, "group_lock_phrase_enabled", False))
        schedule_enabled = bool(getattr(settings, "group_lock_schedule_enabled", False))

        text = (
            "📢 关群设置\n\n"
            "根据管理员话术进行全员禁言，或者定时全员禁言，用来防范半夜管理不在是产生违规内容。\n\n"
            "话术关群：\n"
            "└ 输入开群词，打开全员聊天\n"
            "└ 输入关群词，关闭全员聊天\n"
            "└ 拥有添加管理员权限的管理员可用\n\n"
            f"⏰ 定时关群（{'已开启' if schedule_enabled else '已关闭'}）\n"
            f"└ 下次开启时间：{open_time}\n"
            f"└ 下次关停时间：{close_time}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 话术开关：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(on_label(phrase_enabled), callback_data=f"adm:gl:{chat_id}:set:phrase:1"),
                InlineKeyboardButton(off_label(phrase_enabled), callback_data=f"adm:gl:{chat_id}:set:phrase:0"),
            ],
            [
                InlineKeyboardButton("💬 开群词：", callback_data=f"adm:gl:{chat_id}:input:open_phrase"),
                InlineKeyboardButton(open_phrase[:12], callback_data=f"adm:gl:{chat_id}:input:open_phrase"),
            ],
            [
                InlineKeyboardButton("📢 关群词：", callback_data=f"adm:gl:{chat_id}:input:close_phrase"),
                InlineKeyboardButton(close_phrase[:12], callback_data=f"adm:gl:{chat_id}:input:close_phrase"),
            ],
            [
                InlineKeyboardButton("⚙️ 定时开关：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(on_label(schedule_enabled), callback_data=f"adm:gl:{chat_id}:set:schedule:1"),
                InlineKeyboardButton(off_label(schedule_enabled), callback_data=f"adm:gl:{chat_id}:set:schedule:0"),
            ],
            [
                InlineKeyboardButton("⏰ 开群时间", callback_data=f"adm:gl:{chat_id}:input:open_time"),
                InlineKeyboardButton(open_time, callback_data=f"adm:gl:{chat_id}:input:open_time"),
            ],
            [
                InlineKeyboardButton("⏰ 关群时间", callback_data=f"adm:gl:{chat_id}:input:close_time"),
                InlineKeyboardButton(close_time, callback_data=f"adm:gl:{chat_id}:input:close_time"),
            ],
            [
                InlineKeyboardButton("🧹 删除通知消息：", callback_data=f"adm:menu:closegroup:{chat_id}"),
                InlineKeyboardButton(
                    delete_label,
                    callback_data=f"adm:gl:{chat_id}:notice:{'keep' if delete_label == '删除' else 'delete'}",
                ),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_rename_monitor_menu(
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

        enabled = bool(getattr(settings, "name_change_monitor_enabled", False))
        template = getattr(settings, "name_change_monitor_template_text", "") or "未设置"
        delete_after = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)
        text = (
            "🕵️ 用户改名监控\n\n"
            "当监控到用户改变昵称或者用户名，会根据本页设置发送通知到群。\n\n"
            f"状态: {'✅ 启动' if enabled else '❌ 关闭'}\n"
            f"删除提示消息: {delete_after}秒后删除\n\n"
            f"当前文案:\n{template}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton("✅ 启用" if enabled else "启用", callback_data=f"adm:rm:{chat_id}:set:enabled:1"),
                InlineKeyboardButton("❌ 关闭" if not enabled else "关闭", callback_data=f"adm:rm:{chat_id}:set:enabled:0"),
            ],
            [InlineKeyboardButton("📝 设置提示消息", callback_data=f"adm:rm:{chat_id}:input:text")],
            [InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:rm:{chat_id}:preview")],
            [
                InlineKeyboardButton("🧹 删除提示消息：", callback_data=f"adm:menu:renamewatch:{chat_id}"),
                InlineKeyboardButton(f"{delete_after}秒后删除", callback_data=f"adm:rm:{chat_id}:cycle_delete_after"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
