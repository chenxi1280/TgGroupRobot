from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.features.admin.support import *
from backend.features.group_ops.services.bottom_button_events import (
    decode_event_callback_key,
)


@dataclass(frozen=True)
class BottomButtonDependencies:
    update_setting: Callable
    generate: Callable
    get_setting: Callable
    add_layout: Callable
    clear_layouts: Callable
    get_layout: Callable
    find_event: Callable
    update_layout: Callable
    delete_layout: Callable


class BottomButtonActionMixin:
    async def _handle_bottom_button(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_bottom_button_menu(update, context, chat_id)
            return
        async with db.session_factory() as session:
            if await self._handle_bottom_general(
                update,
                context,
                session=session,
                chat_id=chat_id,
                action=action,
                callback_data=callback_data,
            ):
                return
            if action == "layout":
                await self._handle_bottom_layout(
                    update,
                    context,
                    session=session,
                    chat_id=chat_id,
                    callback_data=callback_data,
                )
                return
            if action == "button":
                await self._handle_bottom_layout_button(
                    update,
                    context,
                    session=session,
                    chat_id=chat_id,
                    callback_data=callback_data,
                )
                return
            await self._handle_bottom_terminal(
                update,
                context,
                session=session,
                chat_id=chat_id,
                action=action,
                callback_data=callback_data,
            )

    async def _handle_bottom_general(
        self, update, context, *, session, chat_id: int, action: str, callback_data
    ) -> bool:
        deps = self._bottom_button_dependencies()
        if action == "toggle":
            enabled = callback_data.get(3) == "1"
            await deps.update_setting(session, chat_id, enabled=enabled)
            if enabled:
                await deps.generate(context, session, chat_id)
            await session.commit()
            await self._show_bottom_button_menu(update, context, chat_id)
            return True
        if action != "text" or callback_data.get(3) != "edit":
            return False
        user_id = update.effective_user.id
        await self._start_text_input_state(
            context,
            user_id,
            user_id,
            state_type="bottom_button_text_input",
            payload={"target_chat_id": chat_id},
        )
        setting = await deps.get_setting(session, chat_id)
        await session.commit()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"btm:home:{chat_id}")]]
        )
        text = f"⌨️ 底部按钮 | 修改文本内容\n\n当前的文本内容：\n{setting.header_text}\n\n👉 现在输入新的文本内容："
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
        return True

    async def _sync_bottom_layout(self, context, session, chat_id: int) -> None:
        deps = self._bottom_button_dependencies()
        setting = await deps.get_setting(session, chat_id)
        if setting.enabled:
            await deps.generate(context, session, chat_id)

    async def _handle_bottom_layout(
        self, update, context, *, session, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(3)
        if sub == "edit":
            await session.commit()
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return
        if sub == "add":
            if not await self._add_bottom_layout(
                update,
                context,
                session=session,
                chat_id=chat_id,
                callback_data=callback_data,
            ):
                return
        elif sub == "clear":
            await self._bottom_button_dependencies().clear_layouts(session, chat_id)
        else:
            return
        await self._sync_bottom_layout(context, session, chat_id)
        await session.commit()
        await self._show_bottom_button_layout_menu(update, context, chat_id)

    async def _add_bottom_layout(
        self, update, context, *, session, chat_id: int, callback_data
    ) -> bool:
        row_no = callback_data.get_int_optional(4)
        col_no = callback_data.get_int_optional(5)
        try:
            await self._bottom_button_dependencies().add_layout(
                session, chat_id, row_no=row_no, col_no=col_no
            )
            return True
        except ValidationError as exc:
            log.warning(
                "bottom_button_layout_add_validation_failed",
                chat_id=chat_id,
                row_no=row_no,
                col_no=col_no,
                error=str(exc),
            )
            await session.commit()
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return False

    async def _handle_bottom_layout_button(
        self, update, context, *, session, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(3)
        layout_id = callback_data.get_int(4)
        if await self._handle_bottom_button_view(
            update,
            context,
            session=session,
            chat_id=chat_id,
            layout_id=layout_id,
            sub=sub,
            callback_data=callback_data,
        ):
            return
        if sub == "event":
            await self._bind_bottom_button_event(
                update,
                context,
                session=session,
                chat_id=chat_id,
                layout_id=layout_id,
                callback_data=callback_data,
            )
            return
        if sub in {"text", "payload"}:
            await self._start_bottom_button_input(
                update,
                context,
                session=session,
                chat_id=chat_id,
                layout_id=layout_id,
                sub=sub,
            )
            return
        await self._mutate_bottom_button(
            update,
            context,
            session=session,
            chat_id=chat_id,
            layout_id=layout_id,
            sub=sub,
            callback_data=callback_data,
        )

    async def _handle_bottom_button_view(
        self,
        update,
        context,
        *,
        session,
        chat_id: int,
        layout_id: int,
        sub: str,
        callback_data,
    ) -> bool:
        if sub not in {"detail", "events", "eventcat"}:
            return False
        await session.commit()
        if sub == "detail":
            await self._show_bottom_button_detail(
                update, context, chat_id, layout_id=layout_id
            )
        elif sub == "events":
            await self._show_bottom_button_event_menu(
                update, context, chat_id, layout_id=layout_id
            )
        else:
            await self._show_bottom_button_event_list(
                update,
                context,
                chat_id,
                layout_id=layout_id,
                category=callback_data.get(5),
            )
        return True

    async def _bind_bottom_button_event(
        self,
        update,
        context,
        *,
        session,
        chat_id: int,
        layout_id: int,
        callback_data,
    ) -> None:
        event_key = decode_event_callback_key(callback_data.get(5))
        deps = self._bottom_button_dependencies()
        layout = await deps.get_layout(session, chat_id, layout_id)
        event = await deps.find_event(session, chat_id, event_key)
        if layout is None:
            await session.commit()
            await answer_callback_query_safely(update, "❌ 按钮不存在", show_alert=True)
            await self._show_bottom_button_layout_menu(update, context, chat_id)
            return
        if event is None:
            await session.commit()
            await answer_callback_query_safely(update, "事件类型无效", show_alert=True)
            await self._show_bottom_button_event_menu(
                update, context, chat_id, layout_id=layout_id
            )
            return
        default_text = (
            not (layout.button_text or "").strip() or layout.button_text == "按钮"
        )
        await deps.update_layout(
            session,
            chat_id=chat_id,
            layout_id=layout_id,
            button_text=event.default_button_text if default_text else None,
            action_mode="event",
            payload_text=event_key,
        )
        await self._sync_bottom_layout(context, session, chat_id)
        await session.commit()
        await self._show_bottom_button_detail(
            update, context, chat_id, layout_id=layout_id
        )

    async def _start_bottom_button_input(
        self, update, context, *, session, chat_id: int, layout_id: int, sub: str
    ) -> None:
        is_text = sub == "text"
        user_id = update.effective_user.id
        await self._start_text_input_state(
            context,
            user_id,
            user_id,
            state_type="bottom_button_button_text_input"
            if is_text
            else "bottom_button_payload_input",
            payload={"target_chat_id": chat_id, "layout_id": layout_id},
        )
        await session.commit()
        title = "⌨️ 底部按钮 | 编辑按钮文字" if is_text else "⌨️ 底部按钮 | 编辑按钮内容"
        prompt = "👉 现在输入按钮文字：" if is_text else "👉 现在输入按钮发送内容："
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 返回",
                        callback_data=f"btm:button:{chat_id}:detail:{layout_id}",
                    )
                ]
            ]
        )
        await self.message_helper.safe_edit(
            update, f"{title}\n\n{prompt}", reply_markup=keyboard
        )

    async def _mutate_bottom_button(
        self,
        update,
        context,
        *,
        session,
        chat_id: int,
        layout_id: int,
        sub: str,
        callback_data,
    ) -> None:
        if sub == "mode":
            await self._bottom_button_dependencies().update_layout(
                session,
                chat_id=chat_id,
                layout_id=layout_id,
                action_mode=callback_data.get(5),
            )
            show_detail = True
        elif sub == "delete":
            await self._bottom_button_dependencies().delete_layout(
                session, chat_id, layout_id
            )
            show_detail = False
        else:
            return
        await self._sync_bottom_layout(context, session, chat_id)
        await session.commit()
        if show_detail:
            await self._show_bottom_button_detail(
                update, context, chat_id, layout_id=layout_id
            )
        else:
            await self._show_bottom_button_layout_menu(update, context, chat_id)

    async def _handle_bottom_terminal(
        self, update, context, *, session, chat_id: int, action: str, callback_data
    ) -> None:
        if action == "generate" and callback_data.get(3) == "now":
            deps = self._bottom_button_dependencies()
            await deps.update_setting(session, chat_id, enabled=True)
            await deps.generate(context, session, chat_id)
            message = None
        elif action == "repeat":
            await self._bottom_button_dependencies().update_setting(
                session, chat_id, repeat_generate_enabled=False
            )
            message = "底部键盘不需要重复生成，已保持关闭。"
        else:
            return
        await session.commit()
        if message:
            await answer_callback_query_safely(update, message)
        await self._show_bottom_button_menu(update, context, chat_id)
