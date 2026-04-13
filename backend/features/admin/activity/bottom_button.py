from __future__ import annotations

from backend.features.admin.support import *

class BottomButtonAdminControllerMixin:
    async def _show_bottom_button_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_bottom_button_setting(session, chat_id)
            layouts = await list_bottom_button_layouts(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "⌨️ 底部按钮",
                "",
                f"⚙️ 状态：{'✅ 启用' if setting.enabled else '❌ 关闭'}",
                f"📝 文案：{setting.header_text}",
                f"🔢 按钮数：{len(layouts)}",
                f"⏱ 重复生成：{'✅ 启用' if setting.repeat_generate_enabled else '❌ 关闭'}",
                "",
                "提示：发送模式会由 Bot 直接发出内容；填充模式会把内容填到当前输入框。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"btm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启用" if setting.enabled else "启用", callback_data=f"btm:toggle:{chat_id}:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.enabled else "关闭", callback_data=f"btm:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("✏️ 文案设置", callback_data=f"btm:text:{chat_id}:edit"),
                InlineKeyboardButton("⌨️ 按钮设置", callback_data=f"btm:layout:{chat_id}:edit"),
            ],
            [
                InlineKeyboardButton("✅ 立刻生成", callback_data=f"btm:generate:{chat_id}:now"),
                InlineKeyboardButton(("✅ " if setting.repeat_generate_enabled else "⏱ ") + "重复生成", callback_data=f"btm:repeat:{chat_id}:{0 if setting.repeat_generate_enabled else 1}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_bottom_button_layout_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layouts = await compact_bottom_button_layouts(session, chat_id)
            await session.commit()

        grid: list[list[InlineKeyboardButton]] = []
        position_map = {(item.row_no, item.col_no): item for item in layouts}
        max_row = max([item.row_no for item in layouts], default=1)
        for row_no in range(1, min(max_row + 1, 3) + 1):
            row: list[InlineKeyboardButton] = []
            for col_no in range(1, 5):
                item = position_map.get((row_no, col_no))
                if item is None:
                    row.append(InlineKeyboardButton("➕ 按钮", callback_data=f"btm:layout:{chat_id}:add"))
                else:
                    row.append(InlineKeyboardButton(item.button_text, callback_data=f"btm:button:{chat_id}:detail:{item.id}"))
            grid.append(row)
        keyboard_rows = [
            *grid,
            [
                InlineKeyboardButton("♻️ 清空按钮", callback_data=f"btm:layout:{chat_id}:clear"),
                InlineKeyboardButton("🔙 返回", callback_data=f"btm:home:{chat_id}"),
            ],
        ]
        text = "\n".join(
            [
                "⌨️ 底部按钮 | 按钮设置",
                "",
                "先配置按钮布局（每行最多4个按钮）再点击按钮配置文案。",
                "",
                build_management_layout_preview(layouts),
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_bottom_button_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        layout_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layout = await get_bottom_button_layout(session, chat_id, layout_id)
            await session.commit()
        if layout is None:
            await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return
        text = "\n".join(
            [
                "⌨️ 底部按钮 | 编辑按钮",
                "",
                f"按钮文字：{layout.button_text}",
                f"发送内容：{layout.payload_text or layout.button_text}",
                f"当前模式：{'📨 直接发送' if layout.action_mode == 'send' else '✍️ 仅填充'}",
                "",
                "建议按钮文字不超过 4 个字。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ 修改文字", callback_data=f"btm:button:{chat_id}:text:{layout.id}"),
                InlineKeyboardButton("📝 修改内容", callback_data=f"btm:button:{chat_id}:payload:{layout.id}"),
            ],
            [
                InlineKeyboardButton("📨 直接发送" + (" ✅" if layout.action_mode == "send" else ""), callback_data=f"btm:button:{chat_id}:mode:{layout.id}:send"),
                InlineKeyboardButton("✍️ 仅填充" + (" ✅" if layout.action_mode == "fill" else ""), callback_data=f"btm:button:{chat_id}:mode:{layout.id}:fill"),
            ],
            [
                InlineKeyboardButton("❌ 删除按钮", callback_data=f"btm:button:{chat_id}:delete:{layout.id}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"btm:layout:{chat_id}:edit"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _handle_bottom_button(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_bottom_button_menu(update, context, chat_id)
            return

        async with db.session_factory() as session:
            if action == "toggle":
                await update_bottom_button_setting(session, chat_id, enabled=callback_data.get(3) == "1")
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return
            if action == "text" and callback_data.get(3) == "edit":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    update.effective_user.id,
                    "bottom_button_text_input",
                    {"target_chat_id": chat_id},
                )
                setting = await get_bottom_button_setting(session, chat_id)
                await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    f"⌨️ 底部按钮 | 修改文本内容\n\n当前的文本内容：\n{setting.header_text}\n\n👉 现在输入新的文本内容：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"btm:home:{chat_id}")]]),
                )
                return
            if action == "layout":
                sub = callback_data.get(3)
                if sub == "edit":
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub == "add":
                    await add_layout_button(session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub == "clear":
                    await clear_bottom_button_layouts(session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
            if action == "button":
                sub = callback_data.get(3)
                layout_id = callback_data.get_int(4)
                if sub == "detail":
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "mode":
                    await update_layout_button(session, chat_id=chat_id, layout_id=layout_id, action_mode=callback_data.get(5))
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "delete":
                    await delete_layout_button(session, chat_id, layout_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub in {"text", "payload"}:
                    state_type = "bottom_button_button_text_input" if sub == "text" else "bottom_button_payload_input"
                    await self._start_text_input_state(
                        context,
                        update.effective_user.id,
                        update.effective_user.id,
                        state_type,
                        {"target_chat_id": chat_id, "layout_id": layout_id},
                    )
                    await session.commit()
                    prompt = "👉 现在输入按钮文字：" if sub == "text" else "👉 现在输入按钮发送内容："
                    await self.message_helper.safe_edit(
                        update,
                        ("⌨️ 底部按钮 | 编辑按钮文字" if sub == "text" else "⌨️ 底部按钮 | 编辑按钮内容") + f"\n\n{prompt}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"btm:button:{chat_id}:detail:{layout_id}")]]),
                    )
                    return
            if action == "generate" and callback_data.get(3) == "now":
                await update_bottom_button_setting(session, chat_id, enabled=True)
                await generate_bottom_buttons(context, session, chat_id)
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return
            if action == "repeat":
                await update_bottom_button_setting(session, chat_id, repeat_generate_enabled=callback_data.get(3) == "1")
                await session.commit()
                await self._show_bottom_button_menu(update, context, chat_id)
                return
