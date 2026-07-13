from __future__ import annotations

from backend.features.admin.activity.bottom_button_actions import (
    BottomButtonActionMixin,
    BottomButtonDependencies,
)
from backend.features.admin.activity.bottom_button_presenters import (
    build_bottom_detail,
    build_bottom_event_categories,
    build_bottom_event_list,
    build_bottom_home,
)
from backend.features.admin.support import *
from backend.features.group_ops.services.bottom_button_service import (
    MAX_BUTTON_COLS,
    MAX_LAYOUT_ROWS,
)
from backend.features.group_ops.services.bottom_button_events import (
    BOTTOM_BUTTON_EVENT_CATEGORIES,
    CUSTOM_TRIGGER_CATEGORY,
    encode_event_callback_key,
    find_bottom_button_event,
    list_bottom_button_events,
)


def _build_bottom_layout_row(layouts, position_map, *, chat_id: int, row_no: int):
    row = []
    row_items = [item for item in layouts if item.row_no == row_no]
    last_col = min(max((item.col_no for item in row_items), default=0), MAX_BUTTON_COLS)
    show_until = min(last_col + 1, MAX_BUTTON_COLS) if row_items else 1
    for col_no in range(1, show_until + 1):
        item = position_map.get((row_no, col_no))
        if item is not None:
            row.append(
                InlineKeyboardButton(
                    item.button_text,
                    callback_data=f"btm:button:{chat_id}:detail:{item.id}",
                )
            )
            continue
        has_later = any(existing.col_no > col_no for existing in row_items)
        label = "⚠️ 空" if has_later else "➕ 按钮"
        row.append(
            InlineKeyboardButton(
                label, callback_data=f"btm:layout:{chat_id}:add:{row_no}:{col_no}"
            )
        )
    return row


def _build_bottom_layout_grid(layouts, chat_id: int):
    position_map = {(item.row_no, item.col_no): item for item in layouts}
    max_row = max([item.row_no for item in layouts], default=0)
    display_rows = min(max(max_row + 1, 1), MAX_LAYOUT_ROWS)
    return [
        _build_bottom_layout_row(layouts, position_map, chat_id=chat_id, row_no=row_no)
        for row_no in range(1, display_rows + 1)
    ]


class BottomButtonAdminControllerMixin(BottomButtonActionMixin):
    def _bottom_button_dependencies(self) -> BottomButtonDependencies:
        return BottomButtonDependencies(
            update_setting=update_bottom_button_setting,
            generate=generate_bottom_buttons,
            get_setting=get_bottom_button_setting,
            add_layout=add_layout_button,
            clear_layouts=clear_bottom_button_layouts,
            get_layout=get_bottom_button_layout,
            find_event=find_bottom_button_event,
            update_layout=update_layout_button,
            delete_layout=delete_layout_button,
        )

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
        text, keyboard = build_bottom_home(setting, layouts, chat_id)
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

        grid = _build_bottom_layout_grid(layouts, chat_id)
        keyboard_rows = [
            *grid,
            [
                InlineKeyboardButton(
                    "♻️ 清空按钮", callback_data=f"btm:layout:{chat_id}:clear"
                ),
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
        await self.message_helper.safe_edit(
            update, text=text, reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )

    async def _show_bottom_button_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
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
        text, keyboard = build_bottom_detail(
            layout, chat_id, describe_layout_action(layout)
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_bottom_button_event_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
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

        text, keyboard = build_bottom_event_categories(
            layout,
            BOTTOM_BUTTON_EVENT_CATEGORIES,
            chat_id,
            custom_category=CUSTOM_TRIGGER_CATEGORY,
            action_label=describe_layout_action(layout),
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_bottom_button_event_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        layout_id: int,
        category: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            layout = await get_bottom_button_layout(session, chat_id, layout_id)
            events = await list_bottom_button_events(
                session, chat_id, category=category
            )
            await session.commit()
        if layout is None:
            await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return

        category_label = dict(BOTTOM_BUTTON_EVENT_CATEGORIES).get(category, "事件")
        text, keyboard = build_bottom_event_list(
            layout,
            events,
            chat_id,
            category_label=category_label,
            action_label=describe_layout_action(layout),
            encode_key=encode_event_callback_key,
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
