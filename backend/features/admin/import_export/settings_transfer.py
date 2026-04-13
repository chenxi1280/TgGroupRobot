from __future__ import annotations

from backend.features.admin.support import *


class SettingsTransferAdminMixin:
    async def _show_import_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        state = _get_import_state(context, update.effective_user.id, chat_id, mode="import")
        source_chat_id = state.get("source_chat_id")
        modules = set(state.get("modules", []))

        db: Database = context.application.bot_data["db"]
        chat_title = await self._get_chat_title(db, chat_id)

        source_title = "未选择"
        if source_chat_id:
            source_title = await self._get_chat_title(db, source_chat_id)

        lines = [
            "📥 导入设置",
            "",
            f"目标群组：{chat_title}",
            f"来源群组：{source_title}",
            "",
            "已选模块：",
        ]
        module_defs = list_import_modules()
        if modules:
            for item in module_defs:
                if item["key"] in modules:
                    lines.append(f"✅ {item['label']}")
        else:
            lines.append("未选择")
        lines.extend(
            [
                "",
                "导入会覆盖目标群组对应模块的配置。",
                "欢迎/自动回复/违禁词会覆盖原有条目。",
            ]
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 选择来源群", callback_data=f"adm:import:{chat_id}:pick_source")],
            [InlineKeyboardButton("🧩 选择模块", callback_data=f"adm:import:{chat_id}:pick_modules")],
            [
                InlineKeyboardButton("✅ 全选模块", callback_data=f"adm:import:{chat_id}:select_all"),
                InlineKeyboardButton("🧹 清空选择", callback_data=f"adm:import:{chat_id}:clear"),
            ],
            [InlineKeyboardButton("🚀 执行导入", callback_data=f"adm:import:{chat_id}:apply")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_clone_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        state = _get_import_state(context, update.effective_user.id, chat_id, mode="clone")
        target_chat_id = state.get("target_chat_id")
        modules = set(state.get("modules", []))

        db: Database = context.application.bot_data["db"]
        source_title = await self._get_chat_title(db, chat_id)
        target_title = "未选择"
        if target_chat_id and target_chat_id != chat_id:
            target_title = await self._get_chat_title(db, target_chat_id)

        lines = [
            "📋 克隆设置",
            "",
            f"来源群组：{source_title}",
            f"目标群组：{target_title}",
            "",
            "已选模块：",
        ]
        module_defs = list_import_modules()
        if modules:
            for item in module_defs:
                if item["key"] in modules:
                    lines.append(f"✅ {item['label']}")
        else:
            lines.append("未选择")
        lines.extend(
            [
                "",
                "克隆会覆盖目标群组对应模块的配置。",
                "欢迎/自动回复/违禁词会覆盖原有条目。",
            ]
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 选择目标群", callback_data=f"adm:clone:{chat_id}:pick_target")],
            [InlineKeyboardButton("🧩 选择模块", callback_data=f"adm:clone:{chat_id}:pick_modules")],
            [
                InlineKeyboardButton("✅ 全选模块", callback_data=f"adm:clone:{chat_id}:select_all"),
                InlineKeyboardButton("🧹 清空选择", callback_data=f"adm:clone:{chat_id}:clear"),
            ],
            [InlineKeyboardButton("🚀 执行克隆", callback_data=f"adm:clone:{chat_id}:apply")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _handle_import_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        state = _get_import_state(context, update.effective_user.id, chat_id, mode="import")
        modules = set(state.get("modules", []))

        if op == "pick_source":
            keyboard = await self._build_import_source_keyboard(update, context, target_chat_id=chat_id, mode="import")
            await self.message_helper.safe_edit(update, "请选择来源群：", reply_markup=keyboard)
            return

        if op == "source":
            source_chat_id = callback_data.get_int_optional(4)
            if source_chat_id is None or source_chat_id == chat_id:
                await answer_callback_query_safely(update, "来源群无效", show_alert=True)
                return
            state["source_chat_id"] = source_chat_id
            await self._show_import_settings_menu(update, context, chat_id)
            return

        if op == "pick_modules":
            rows: list[list[InlineKeyboardButton]] = []
            for item in list_import_modules():
                key = item["key"]
                selected = "✅" if key in modules else "❌"
                rows.append([InlineKeyboardButton(f"{selected} {item['label']}", callback_data=f"adm:import:{chat_id}:module:{key}")])
            rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:import:{chat_id}")])
            await self.message_helper.safe_edit(update, "选择要导入的模块：", reply_markup=InlineKeyboardMarkup(rows))
            return

        if op == "module":
            key = callback_data.get(4)
            keys = {item["key"] for item in list_import_modules()}
            if key not in keys:
                await answer_callback_query_safely(update, "未识别的模块", show_alert=True)
                return
            if key in modules:
                modules.remove(key)
            else:
                modules.add(key)
            state["modules"] = list(modules)
            await self._handle_import_settings(update, context, chat_id, CallbackParser.parse(f"adm:import:{chat_id}:pick_modules"))
            return

        if op == "select_all":
            state["modules"] = [item["key"] for item in list_import_modules()]
            await self._show_import_settings_menu(update, context, chat_id)
            return

        if op == "clear":
            state["modules"] = []
            state["source_chat_id"] = None
            await self._show_import_settings_menu(update, context, chat_id)
            return

        if op == "apply":
            source_chat_id = state.get("source_chat_id")
            if not source_chat_id:
                await answer_callback_query_safely(update, "请先选择来源群", show_alert=True)
                return
            if not modules:
                await answer_callback_query_safely(update, "请至少选择一个模块", show_alert=True)
                return
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                await apply_import(
                    session,
                    source_chat_id=source_chat_id,
                    target_chat_id=chat_id,
                    modules=list(modules),
                )
                await session.commit()
            state["modules"] = []
            await self.message_helper.safe_edit(
                update,
                "✅ 导入完成",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:import:{chat_id}")]]),
            )
            return

        await self._show_import_settings_menu(update, context, chat_id)

    async def _handle_clone_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        state = _get_import_state(context, update.effective_user.id, chat_id, mode="clone")
        modules = set(state.get("modules", []))

        if op == "pick_target":
            keyboard = await self._build_import_source_keyboard(update, context, target_chat_id=chat_id, mode="clone")
            await self.message_helper.safe_edit(update, "请选择目标群：", reply_markup=keyboard)
            return

        if op == "target":
            target_chat_id = callback_data.get_int_optional(4)
            if target_chat_id is None or target_chat_id == chat_id:
                await answer_callback_query_safely(update, "目标群无效", show_alert=True)
                return
            state["target_chat_id"] = target_chat_id
            await self._show_clone_settings_menu(update, context, chat_id)
            return

        if op == "pick_modules":
            rows: list[list[InlineKeyboardButton]] = []
            for item in list_import_modules():
                key = item["key"]
                selected = "✅" if key in modules else "❌"
                rows.append([InlineKeyboardButton(f"{selected} {item['label']}", callback_data=f"adm:clone:{chat_id}:module:{key}")])
            rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:clone:{chat_id}")])
            await self.message_helper.safe_edit(update, "选择要克隆的模块：", reply_markup=InlineKeyboardMarkup(rows))
            return

        if op == "module":
            key = callback_data.get(4)
            keys = {item["key"] for item in list_import_modules()}
            if key not in keys:
                await answer_callback_query_safely(update, "未识别的模块", show_alert=True)
                return
            if key in modules:
                modules.remove(key)
            else:
                modules.add(key)
            state["modules"] = list(modules)
            await self._handle_clone_settings(update, context, chat_id, CallbackParser.parse(f"adm:clone:{chat_id}:pick_modules"))
            return

        if op == "select_all":
            state["modules"] = [item["key"] for item in list_import_modules()]
            await self._show_clone_settings_menu(update, context, chat_id)
            return

        if op == "clear":
            state["modules"] = []
            state["target_chat_id"] = None
            await self._show_clone_settings_menu(update, context, chat_id)
            return

        if op == "apply":
            target_chat_id = state.get("target_chat_id")
            if not target_chat_id:
                await answer_callback_query_safely(update, "请先选择目标群", show_alert=True)
                return
            if not modules:
                await answer_callback_query_safely(update, "请至少选择一个模块", show_alert=True)
                return
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                await apply_import(
                    session,
                    source_chat_id=chat_id,
                    target_chat_id=target_chat_id,
                    modules=list(modules),
                )
                await session.commit()
            state["modules"] = []
            await self.message_helper.safe_edit(
                update,
                "✅ 克隆完成",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:clone:{chat_id}")]]),
            )
            return

        await self._show_clone_settings_menu(update, context, chat_id)
