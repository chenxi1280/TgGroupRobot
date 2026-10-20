from __future__ import annotations

from backend.shared.ui.admin_keyboard import admin_keyboard

from backend.shared.callback_parser import CallbackData

from backend.features.admin.support import *
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService


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
            f"目标群组：{chat_title}（{chat_id}）",
            f"来源群组：{source_title}（{source_chat_id or '未选择'}）",
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
                "主积分含签到反馈；夜间管控含双权限/通知，保留目标群原权限快照。",
                "积分等级与标签会重建等级编号映射；不复制余额、已有标签所有权或执行记录。已启用策略将由后台消费。",
            ]
        )

        keyboard = admin_keyboard([
            [InlineKeyboardButton("👥 选择来源群", callback_data=f"adm:import:{chat_id}:pick_source")],
            [InlineKeyboardButton("🧩 选择模块", callback_data=f"adm:import:{chat_id}:pick_modules")],
            [
                InlineKeyboardButton("✅ 全选模块", callback_data=f"adm:import:{chat_id}:select_all"),
                InlineKeyboardButton("🧹 清空选择", callback_data=f"adm:import:{chat_id}:clear"),
            ],
            [InlineKeyboardButton("🚀 执行导入", callback_data=f"adm:import:{chat_id}:apply")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_system:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_transfer_menu(self, update, context, chat_id: int, *, mode: str) -> None:
        if mode == "import":
            await self._show_import_settings_menu(update, context, chat_id)
            return
        await self._show_clone_settings_menu(update, context, chat_id)

    async def _show_transfer_module_picker(self, update, chat_id: int, modules: set, *, mode: str) -> None:
        rows = []
        for item in list_import_modules():
            selected = "✅" if item["key"] in modules else "❌"
            callback = f"adm:{mode}:{chat_id}:module:{item['key']}"
            rows.append([InlineKeyboardButton(f"{selected} {item['label']}", callback_data=callback)])
        rows.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:" + mode + f":{chat_id}")])
        action_name = "导入" if mode == "import" else "克隆"
        await self.message_helper.safe_edit(update, f"群：{chat_id}\n选择要{action_name}的模块：\n点选切换勾选；返回设置页后再执行。", reply_markup=admin_keyboard(rows))

    async def _set_transfer_chat(self, update, context, chat_id: int, *, callback_data, state, mode: str) -> None:
        selected_chat_id = callback_data.get_int_optional(4)
        label = "来源群" if mode == "import" else "目标群"
        if selected_chat_id is None or selected_chat_id == chat_id:
            await answer_callback_query_safely(update, f"{label}无效", show_alert=True)
            return
        if not await _can_transfer_peer(update, context, selected_chat_id):
            return
        state["source_chat_id" if mode == "import" else "target_chat_id"] = selected_chat_id
        await self._show_transfer_menu(update, context, chat_id, mode=mode)

    async def _toggle_transfer_module(self, update, chat_id: int, *, callback_data, state, modules: set, mode: str) -> None:
        key = callback_data.get(4)
        if key not in {item["key"] for item in list_import_modules()}:
            await answer_callback_query_safely(update, "未识别的模块", show_alert=True)
            return
        modules = modules - {key} if key in modules else modules | {key}
        state["modules"] = list(modules)
        await self._show_transfer_module_picker(update, chat_id, modules, mode=mode)

    async def _apply_settings_transfer(self, update, context, chat_id: int, *, state, modules: set, mode: str) -> None:
        peer_key = "source_chat_id" if mode == "import" else "target_chat_id"
        peer_chat_id = state.get(peer_key)
        peer_label = "来源群" if mode == "import" else "目标群"
        if not peer_chat_id:
            await answer_callback_query_safely(update, f"请先选择{peer_label}", show_alert=True)
            return
        if not modules:
            await answer_callback_query_safely(update, "请至少选择一个模块", show_alert=True)
            return
        if not await _can_transfer_peer(update, context, peer_chat_id):
            return
        source_chat_id, target_chat_id = (peer_chat_id, chat_id) if mode == "import" else (chat_id, peer_chat_id)
        db: Database = context.application.bot_data["db"]
        try:
            async with db.session_factory() as session:
                await apply_import(session, source_chat_id=source_chat_id, target_chat_id=target_chat_id,
                    modules=list(modules), context=context, actor_user_id=update.effective_user.id)
                from backend.shared.services.ops_audit_service import record_ops_event
                await record_ops_event(session,domain='settings_transfer',event_type=mode,chat_id=target_chat_id,
                    user_id=update.effective_user.id,detail={'source_chat_id':source_chat_id,'modules':sorted(modules)})
                await session.commit()
        except ValidationError as exc:
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            return
        state["modules"] = []
        result_label = "导入" if mode == "import" else "克隆"
        callback = "adm:menu:" + mode + f":{chat_id}"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=callback)]])
        await self.message_helper.safe_edit(update, f"✅ {result_label}完成", reply_markup=markup)

    async def _handle_transfer_mutation(self, update, context, chat_id: int, *, op: str, state, modules: set, mode: str) -> bool:
        if op == "select_all":
            state["modules"] = [item["key"] for item in list_import_modules()]
            await self._show_transfer_menu(update, context, chat_id, mode=mode)
            return True
        if op == "clear":
            state["modules"] = []
            state["source_chat_id" if mode == "import" else "target_chat_id"] = None
            await self._show_transfer_menu(update, context, chat_id, mode=mode)
            return True
        if op == "apply":
            await self._apply_settings_transfer(update, context, chat_id, state=state, modules=modules, mode=mode)
            return True
        return False

    async def _handle_settings_transfer(self, update, context, chat_id: int, *, callback_data, mode: str) -> None:
        op = callback_data.get(3)
        state = _get_import_state(context, update.effective_user.id, chat_id, mode=mode)
        modules = set(state.get("modules", []))
        pick_operation = "pick_source" if mode == "import" else "pick_target"
        select_operation = "source" if mode == "import" else "target"
        if op == pick_operation:
            keyboard = await self._build_import_source_keyboard(update, context, target_chat_id=chat_id, mode=mode)
            await self.message_helper.safe_edit(update, "请选择来源群：" if mode == "import" else "请选择目标群：", reply_markup=keyboard)
            return
        if op == select_operation:
            await self._set_transfer_chat(update, context, chat_id, callback_data=callback_data, state=state, mode=mode)
            return
        if op == "pick_modules":
            await self._show_transfer_module_picker(update, chat_id, modules, mode=mode)
            return
        if op == "module":
            await self._toggle_transfer_module(update, chat_id, callback_data=callback_data, state=state, modules=modules, mode=mode)
            return
        if await self._handle_transfer_mutation(
            update, context, chat_id, op=op, state=state, modules=modules, mode=mode
        ):
            return
        await self._show_transfer_menu(update, context, chat_id, mode=mode)

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
            f"来源群组：{source_title}（{chat_id}）",
            f"目标群组：{target_title}（{target_chat_id or '未选择'}）",
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
                "主积分含签到反馈；夜间管控含双权限/通知，保留目标群原权限快照。",
                "积分等级与标签会重建等级编号映射；不复制余额、已有标签所有权或执行记录。已启用策略将由后台消费。",
            ]
        )

        keyboard = admin_keyboard([
            [InlineKeyboardButton("🎯 选择目标群", callback_data=f"adm:clone:{chat_id}:pick_target")],
            [InlineKeyboardButton("🧩 选择模块", callback_data=f"adm:clone:{chat_id}:pick_modules")],
            [
                InlineKeyboardButton("✅ 全选模块", callback_data=f"adm:clone:{chat_id}:select_all"),
                InlineKeyboardButton("🧹 清空选择", callback_data=f"adm:clone:{chat_id}:clear"),
            ],
            [InlineKeyboardButton("🚀 执行克隆", callback_data=f"adm:clone:{chat_id}:apply")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_system:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _handle_import_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData,
    ) -> None:
        await self._handle_settings_transfer(
            update, context, chat_id, callback_data=callback_data, mode="import"
        )

    async def _handle_clone_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData,
    ) -> None:
        await self._handle_settings_transfer(
            update, context, chat_id, callback_data=callback_data, mode="clone"
        )


async def _can_transfer_peer(update, context, peer_chat_id):
    if isinstance(peer_chat_id, int) and peer_chat_id < 0:
        if await PermissionPolicyService.can_manage(context, peer_chat_id, update.effective_user.id):
            return True
    await answer_callback_query_safely(update, "另一端群组无效或已失去管理权限，请重新选择。", show_alert=True)
    return False
