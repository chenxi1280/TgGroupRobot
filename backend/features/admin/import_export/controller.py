from __future__ import annotations

from backend.features.admin.support import *


class ImportExportAdminControllerMixin:
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

    async def _handle_quick_publish(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.shared.services.permission_policy_service import PermissionPolicyService
        from backend.features.garage.services.garage_forward_service import GarageForwardService

        if update.effective_user is None:
            return

        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            chat_id,
            update.effective_user.id,
            capability="automation",
        )
        if not allowed:
            if error_text:
                await answer_callback_query_safely(update, error_text, show_alert=True)
            return

        action = callback_data.get(1)
        if action in {None, "home"}:
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        if action == "input":
            field = callback_data.get(3)
            if field not in {"text", "media", "buttons"}:
                await answer_callback_query_safely(update, "未识别的输入类型", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                update.effective_user.id,
                ConversationStateType.quick_publish_input.value,
                {"target_chat_id": chat_id, "field": field},
            )
            prompt_map = {
                "text": "请输入要发布的文本内容：",
                "media": "请发送要发布的图片/视频/文件（可带说明文字）：",
                "buttons": "请输入按钮配置（文本|链接，每行多个按钮用 ; 分隔，或直接粘贴 JSON）：",
            }
            await self.message_helper.safe_edit(
                update,
                prompt_map[field],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"qpub:home:{chat_id}")]]),
            )
            return

        if action == "clear":
            draft = _get_quick_publish_draft(context, chat_id)
            draft.update({"text": "", "media_type": None, "media_file_id": None, "buttons": []})
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        if action == "send":
            draft = _get_quick_publish_draft(context, chat_id)
            text = (draft.get("text") or "").strip()
            media_type = draft.get("media_type")
            media_file_id = draft.get("media_file_id")
            buttons = draft.get("buttons") or []

            if not text and not media_file_id:
                await answer_callback_query_safely(update, "请先设置文本或媒体内容", show_alert=True)
                return

            reply_markup = None
            if buttons:
                try:
                    reply_markup = GarageForwardService.build_button_markup(buttons)
                except ValidationError as exc:
                    await answer_callback_query_safely(update, str(exc), show_alert=True)
                    return

            if media_file_id:
                if media_type == "photo":
                    await context.bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "video":
                    await context.bot.send_video(chat_id=chat_id, video=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "document":
                    await context.bot.send_document(chat_id=chat_id, document=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "animation":
                    await context.bot.send_animation(chat_id=chat_id, animation=media_file_id, caption=text or None, reply_markup=reply_markup)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=text or "（无文本）", reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

            draft.update({"text": "", "media_type": None, "media_file_id": None, "buttons": []})
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        await self._show_quick_publish_menu(update, context, chat_id)

    async def _show_quick_publish_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示快捷发布菜单。"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        chat_title = await self._get_chat_title(db, chat_id)

        draft = _get_quick_publish_draft(context, chat_id)
        text_preview = (draft.get("text") or "").strip()
        if len(text_preview) > 80:
            text_preview = text_preview[:80] + "..."
        media_type = draft.get("media_type")
        media_label = f"已设置（{media_type}）" if media_type else "未设置"
        buttons_count = len(draft.get("buttons") or [])

        lines = [
            f"⚡ 快捷发布",
            "",
            f"目标群组：{chat_title}",
            f"文本：{text_preview or '未设置'}",
            f"媒体：{media_label}",
            f"按钮：{buttons_count} 行" if buttons_count else "按钮：未设置",
            "",
            "提示：按钮支持 文本|链接 格式，每行多个按钮用 ; 分隔。",
        ]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✍️ 设置文本", callback_data=f"qpub:input:{chat_id}:text"),
                InlineKeyboardButton("🖼️ 设置媒体", callback_data=f"qpub:input:{chat_id}:media"),
            ],
            [
                InlineKeyboardButton("🔗 设置按钮", callback_data=f"qpub:input:{chat_id}:buttons"),
                InlineKeyboardButton("🧹 清空草稿", callback_data=f"qpub:clear:{chat_id}"),
            ],
            [InlineKeyboardButton("🚀 立即发送", callback_data=f"qpub:send:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_account_inherit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            summary = await build_inherit_summary(session, chat_id)
            await session.commit()
        enabled = bool(summary["enabled"])
        text = "\n".join(
            [
                "💥 炸号继承",
                "",
                f"📌 允许继承：{'✅ 允许' if enabled else '❌ 不允许'}",
                f"⏱️ Token 有效期：{summary['token_expire_minutes']} 分钟",
                f"🎟️ 活跃令牌：{summary['active_tokens']}",
                f"🧾 已使用令牌：{summary['used_tokens']}",
                "",
                "旧号生成一次性 token，新号在私聊里使用 token 继承主积分和自定义积分。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("允许继承：", callback_data=f"inh:manage:{chat_id}"),
                InlineKeyboardButton("允许" + (" ✅" if enabled else ""), callback_data=f"inh:toggle:{chat_id}:1"),
                InlineKeyboardButton("不允许" + (" ✅" if not enabled else ""), callback_data=f"inh:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🎟️ 旧号生成令牌", callback_data=f"inh:token:gen:{chat_id}"),
                InlineKeyboardButton("🔓 新号使用令牌", callback_data=f"inh:token:use:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

