from __future__ import annotations

from backend.features.admin.support import *
from backend.features.group_ops.services.bottom_button_service import MAX_BUTTON_COLS, MAX_LAYOUT_ROWS
from backend.features.group_ops.services.bottom_button_events import (
    BOTTOM_BUTTON_EVENT_CATEGORIES,
    CUSTOM_TRIGGER_CATEGORY,
    decode_event_callback_key,
    encode_event_callback_key,
    find_bottom_button_event,
    list_bottom_button_events,
)

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
                "",
                "提示：底部按钮会同步到 Telegram 输入框下方，用户点击后会发送按钮文字并触发对应功能。",
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
                InlineKeyboardButton("✅ 同步到底部键盘", callback_data=f"btm:generate:{chat_id}:now"),
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
            layouts = await list_bottom_button_layouts(session, chat_id)
            await session.commit()

        position_map = {(item.row_no, item.col_no): item for item in layouts}
        max_row = max([item.row_no for item in layouts], default=0)
        display_rows = min(max(max_row + 1, 1), MAX_LAYOUT_ROWS)
        grid: list[list[InlineKeyboardButton]] = []
        for row_no in range(1, display_rows + 1):
            row: list[InlineKeyboardButton] = []
            row_items = [item for item in layouts if item.row_no == row_no]
            if row_items:
                last_col = min(max(item.col_no for item in row_items), MAX_BUTTON_COLS)
                show_until = min(last_col + 1, MAX_BUTTON_COLS)
            else:
                show_until = 1
            for col_no in range(1, show_until + 1):
                item = position_map.get((row_no, col_no))
                if item is None:
                    has_later_button = any(existing.row_no == row_no and existing.col_no > col_no for existing in row_items)
                    label = "⚠️ 空" if has_later_button else "➕ 按钮"
                    row.append(InlineKeyboardButton(label, callback_data=f"btm:layout:{chat_id}:add:{row_no}:{col_no}"))
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
                "⌨️ 底部按钮｜按钮设置",
                "",
                "先配置按钮布局（每行最多4个按钮） 再点击按钮配置文案",
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
                f"绑定事件：{describe_layout_action(layout)}",
                f"点击后发送：{layout.button_text}",
                "",
                "按钮文字展示在输入框下方，绑定事件决定点击后实际执行的功能。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ 修改文字", callback_data=f"btm:button:{chat_id}:text:{layout.id}"),
                InlineKeyboardButton("🎯 绑定事件", callback_data=f"btm:button:{chat_id}:events:{layout.id}"),
            ],
            [InlineKeyboardButton("⌨️ 自定义触发词", callback_data=f"btm:button:{chat_id}:payload:{layout.id}")],
            [
                InlineKeyboardButton("❌ 删除按钮", callback_data=f"btm:button:{chat_id}:delete:{layout.id}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"btm:layout:{chat_id}:edit"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_bottom_button_event_menu(
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

        rows: list[list[InlineKeyboardButton]] = []
        for index in range(0, len(BOTTOM_BUTTON_EVENT_CATEGORIES), 2):
            row: list[InlineKeyboardButton] = []
            for category, label in BOTTOM_BUTTON_EVENT_CATEGORIES[index:index + 2]:
                if category == CUSTOM_TRIGGER_CATEGORY:
                    row.append(InlineKeyboardButton("⌨️ " + label, callback_data=f"btm:button:{chat_id}:payload:{layout.id}"))
                else:
                    row.append(InlineKeyboardButton(label, callback_data=f"btm:button:{chat_id}:eventcat:{layout.id}:{category}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"btm:button:{chat_id}:detail:{layout.id}")])

        text = "\n".join(
            [
                "⌨️ 底部按钮 | 绑定事件",
                "",
                f"按钮文字：{layout.button_text}",
                f"当前绑定：{describe_layout_action(layout)}",
                "",
                "选择一个内置功能事件，或使用自定义触发词兼容群内已有入口。",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(rows))

    async def _show_bottom_button_event_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        layout_id: int,
        category: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layout = await get_bottom_button_layout(session, chat_id, layout_id)
            events = await list_bottom_button_events(session, chat_id, category=category)
            await session.commit()
        if layout is None:
            await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return

        category_label = dict(BOTTOM_BUTTON_EVENT_CATEGORIES).get(category, "事件")
        rows: list[list[InlineKeyboardButton]] = []
        for index in range(0, len(events), 2):
            row = []
            for event in events[index:index + 2]:
                prefix = "✅ " if layout.action_mode == "event" and layout.payload_text == event.key else ""
                row.append(
                    InlineKeyboardButton(
                        prefix + event.label,
                        callback_data=(
                            f"btm:button:{chat_id}:event:{layout.id}:"
                            f"{encode_event_callback_key(event.key)}"
                        ),
                    )
                )
            rows.append(row)
        if not rows:
            rows.append([InlineKeyboardButton("暂无可绑定事件", callback_data=f"btm:button:{chat_id}:events:{layout.id}")])
        rows.append([InlineKeyboardButton("🔙 返回分类", callback_data=f"btm:button:{chat_id}:events:{layout.id}")])

        text = "\n".join(
            [
                f"⌨️ 底部按钮 | {category_label}",
                "",
                f"按钮文字：{layout.button_text}",
                f"当前绑定：{describe_layout_action(layout)}",
                "",
                "选择后会保存为后台事件；如果按钮文字还是“按钮”，会自动改成事件文案。",
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=InlineKeyboardMarkup(rows))

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
                enabled = callback_data.get(3) == "1"
                await update_bottom_button_setting(session, chat_id, enabled=enabled)
                if enabled:
                    await generate_bottom_buttons(context, session, chat_id)
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
                    row_no = callback_data.get_int_optional(4)
                    col_no = callback_data.get_int_optional(5)
                    try:
                        await add_layout_button(session, chat_id, row_no=row_no, col_no=col_no)
                    except ValidationError as exc:
                        await session.commit()
                        await answer_callback_query_safely(update, str(exc), show_alert=True)
                        await self._show_bottom_button_layout_menu(update, context, chat_id)
                        return
                    setting = await get_bottom_button_setting(session, chat_id)
                    if setting.enabled:
                        await generate_bottom_buttons(context, session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_layout_menu(update, context, chat_id)
                    return
                if sub == "clear":
                    await clear_bottom_button_layouts(session, chat_id)
                    setting = await get_bottom_button_setting(session, chat_id)
                    if setting.enabled:
                        await generate_bottom_buttons(context, session, chat_id)
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
                    setting = await get_bottom_button_setting(session, chat_id)
                    if setting.enabled:
                        await generate_bottom_buttons(context, session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "events":
                    await session.commit()
                    await self._show_bottom_button_event_menu(update, context, chat_id, layout_id)
                    return
                if sub == "eventcat":
                    category = callback_data.get(5)
                    await session.commit()
                    await self._show_bottom_button_event_list(update, context, chat_id, layout_id, category)
                    return
                if sub == "event":
                    event_key = decode_event_callback_key(callback_data.get(5))
                    layout = await get_bottom_button_layout(session, chat_id, layout_id)
                    event = await find_bottom_button_event(session, chat_id, event_key)
                    if layout is None:
                        await session.commit()
                        await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
                        await self._show_bottom_button_layout_menu(update, context, chat_id)
                        return
                    if event is None:
                        await session.commit()
                        await answer_callback_query_safely(update, "事件类型无效", show_alert=True)
                        await self._show_bottom_button_event_menu(update, context, chat_id, layout_id)
                        return
                    button_text = event.default_button_text if not (layout.button_text or "").strip() or layout.button_text == "按钮" else None
                    await update_layout_button(
                        session,
                        chat_id=chat_id,
                        layout_id=layout_id,
                        button_text=button_text,
                        action_mode="event",
                        payload_text=event_key,
                    )
                    setting = await get_bottom_button_setting(session, chat_id)
                    if setting.enabled:
                        await generate_bottom_buttons(context, session, chat_id)
                    await session.commit()
                    await self._show_bottom_button_detail(update, context, chat_id, layout_id)
                    return
                if sub == "delete":
                    await delete_layout_button(session, chat_id, layout_id)
                    setting = await get_bottom_button_setting(session, chat_id)
                    if setting.enabled:
                        await generate_bottom_buttons(context, session, chat_id)
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
                await update_bottom_button_setting(session, chat_id, repeat_generate_enabled=False)
                await session.commit()
                await answer_callback_query_safely(update, "底部键盘不需要重复生成，已保持关闭。")
                await self._show_bottom_button_menu(update, context, chat_id)
                return
