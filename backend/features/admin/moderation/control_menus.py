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
        await self._show_night_mode_menu(update, context, chat_id)

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
