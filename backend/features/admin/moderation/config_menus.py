from __future__ import annotations

from backend.features.admin.support import *


def _command_detail_text(command_key: str, entry: dict, definition: dict | None) -> tuple[str, bool]:
    label = definition["label"] if definition else command_key
    enabled = bool(entry.get("enabled", True))
    alias_allowed = definition is None or definition.get("allow_alias", True)
    alias_line = f"别名: {entry.get('alias') or '未设置'}\n" if alias_allowed else ""
    help_text = "你可以设置别名（无需输入 /），或关闭该命令。" if alias_allowed else "该入口为固定中文触发词，只支持启停。"
    text = (
        f"⌨️ 命令配置 | {label}\n\n状态: {'✅ 启用' if enabled else '❌ 关闭'}\n"
        f"{alias_line}\n{help_text}"
    )
    return text, alias_allowed


def _command_detail_rows(chat_id: int, command_key: str, *, enabled: bool, alias_allowed: bool):
    rows = [[
        InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:gcmd:{chat_id}:detail:{command_key}"),
        InlineKeyboardButton("✅ 启用" if enabled else "启用", callback_data=f"adm:gcmd:{chat_id}:toggle:{command_key}"),
        InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:gcmd:{chat_id}:toggle:{command_key}"),
    ]]
    if alias_allowed:
        rows.extend([
            [InlineKeyboardButton("✏️ 设置别名", callback_data=f"adm:gcmd:{chat_id}:alias:{command_key}")],
            [InlineKeyboardButton("🧹 清空别名", callback_data=f"adm:gcmd:{chat_id}:clear_alias:{command_key}")],
        ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:gcmd:{chat_id}")])
    return rows


class ModerationConfigMenusMixin:
    async def _show_command_config_menu(
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

        config_enabled = bool(getattr(settings, "command_config_enabled", False))
        config = get_command_config(settings)
        lines = [
            "⌨️ 群组命令配置",
            "",
            "可对群内常用命令进行启停与别名设置。",
            "",
            f"配置开关: {'✅ 启用' if config_enabled else '❌ 关闭'}",
            "",
            "命令列表：",
        ]
        for item in list_command_definitions():
            key = item["key"]
            label = item["label"]
            entry = config["commands"].get(key, {})
            status = "✅" if entry.get("enabled", True) else "❌"
            alias = entry.get("alias") or "未设置"
            if item.get("allow_alias", True):
                lines.append(f"{status} {label}（别名：{alias}）")
            else:
                lines.append(f"{status} {label}")

        keyboard_rows = [
            [
                InlineKeyboardButton("⚙️ 配置开关", callback_data=f"adm:gcmd:{chat_id}:toggle_enabled"),
                InlineKeyboardButton("✅ 启用" if config_enabled else "启用", callback_data=f"adm:gcmd:{chat_id}:toggle_enabled"),
                InlineKeyboardButton("关闭" if config_enabled else "❌ 关闭", callback_data=f"adm:gcmd:{chat_id}:toggle_enabled"),
            ],
        ]
        for item in list_command_definitions():
            key = item["key"]
            label = item["label"]
            entry = config["commands"].get(key, {})
            status = "✅" if entry.get("enabled", True) else "❌"
            keyboard_rows.append(
                [InlineKeyboardButton(f"{status} {label}", callback_data=f"adm:gcmd:{chat_id}:detail:{key}")]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_command_config_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, command_key: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        config = get_command_config(settings)
        entry = config["commands"].get(command_key)
        if entry is None:
            await answer_callback_query_safely(update, "未识别的命令配置项，请返回后重试", show_alert=True)
            return
        definitions = {item["key"]: item for item in list_command_definitions()}
        definition = definitions.get(command_key)
        enabled = bool(entry.get("enabled", True))
        text, alias_allowed = _command_detail_text(command_key, entry, definition)
        rows = _command_detail_rows(chat_id, command_key, enabled=enabled, alias_allowed=alias_allowed)
        keyboard = InlineKeyboardMarkup(rows)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_punishment_policy_menu(
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

        def _label(action: str) -> str:
            return {
                "delete": "删除",
                "mute": "禁言",
                "ban": "封禁",
                "kick": "踢出",
                "warn": "警告",
            }.get(action or "", action or "未设置")

        lines = [
            "⚖️ 惩罚策略",
            "",
            "统一调整群内常见违规的处理方式。",
            "",
            f"反垃圾：{_label(getattr(settings, 'anti_spam_action', 'delete'))}",
            f"防刷屏：{_label(getattr(settings, 'anti_flood_action', 'delete'))}",
            f"关键词/链接：{_label(getattr(settings, 'moderation_action', 'delete'))}",
            f"验证超时：{_label(getattr(settings, 'verification_timeout_action', 'kick'))}",
            "",
            "提示：验证超时仅支持禁言/踢出，删除模式不会改动验证配置。",
        ]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗑 删除", callback_data=f"adm:punish:{chat_id}:preset:delete"),
                InlineKeyboardButton("🔇 禁言", callback_data=f"adm:punish:{chat_id}:preset:mute"),
                InlineKeyboardButton("⛔ 封禁", callback_data=f"adm:punish:{chat_id}:preset:ban"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_auto_delete_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.admin.ui.auto_delete import auto_delete_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        enabled_keys = [
            bool(getattr(settings, "auto_delete_join", False)),
            bool(getattr(settings, "auto_delete_left", False)),
            bool(getattr(settings, "auto_delete_pinned", False)),
            bool(getattr(settings, "auto_delete_avatar", False)),
            bool(getattr(settings, "auto_delete_title", False)),
            bool(getattr(settings, "auto_delete_anonymous", False)),
        ]
        enabled_labels = [
            label
            for enabled, label in [
                (bool(getattr(settings, "auto_delete_join", False)), "进群"),
                (bool(getattr(settings, "auto_delete_left", False)), "退群"),
                (bool(getattr(settings, "auto_delete_pinned", False)), "置顶"),
                (bool(getattr(settings, "auto_delete_avatar", False)), "头像"),
                (bool(getattr(settings, "auto_delete_title", False)), "群名"),
                (bool(getattr(settings, "auto_delete_anonymous", False)), "匿名消息"),
            ]
            if enabled
        ]
        text = (
            "🧹 删除系统提示\n\n"
            "本功能会自动清除系统提示消息。\n\n"
            f"总开关状态：{'✅ 已生效' if any(enabled_keys) else '❌ 未生效'}\n"
            f"已开启类型：{sum(enabled_keys)}/{len(enabled_keys)}\n"
            f"当前明细：{'、'.join(enabled_labels) if enabled_labels else '暂无'}\n\n"
            "可删除对象：进群 / 退群 / 置顶 / 修改头像 / 修改群名 / 匿名消息。"
        )

        keyboard = auto_delete_config_keyboard(settings, chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_anti_flood_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.admin.ui.antispam import format_garbage_rule_text, garbage_guard_rule_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = format_garbage_rule_text(chat_title, settings, "flood")
        keyboard = garbage_guard_rule_keyboard(settings, chat_id, "flood")
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_antispam_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.admin.ui.antispam import format_garbage_guard_home_text, garbage_guard_home_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = format_garbage_guard_home_text(chat_title, settings)
        keyboard = garbage_guard_home_keyboard(settings, chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
