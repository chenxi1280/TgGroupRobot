from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Chat, Update, User
from telegram.ext import ContextTypes

from backend.features.nearby.nearby_callback_actions import callback_handler_action
from backend.features.nearby.nearby_fsm_actions import (
    handle_clear_action,
    handle_fsm_location_input_action,
    handle_fsm_text_input_action,
    start_edit_state_action,
    toggle_visible_action,
)
from backend.features.nearby.nearby_panels import (
    reply_or_edit,
    show_member_detail,
    show_mydata_panel,
    show_nearby_list,
)
from backend.platform.db.runtime.session import Database
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.shared.services.user_service import ensure_user
from backend.features.group_ops.services.chat_group_service import get_user_current_chat, set_user_current_chat


class NearbyHandler:
    """周边资料与距离查询功能。"""

    async def mydata_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        chat = update.effective_chat
        user = update.effective_user
        db: Database = context.application.bot_data["db"]

        if chat.type in ("group", "supergroup"):
            await self._bind_group_context(db, chat, user)
            text = (
                "✅ 已绑定当前群组。\n\n"
                "请到私聊发送 /mydata 继续编辑资料。\n"
                "你也可以在本群使用 /nearby 查看周边。"
            )
            await update.effective_message.reply_text(text)
            return

        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await update.effective_message.reply_text("请先在目标群发送 /mydata 绑定群组，再来私聊编辑资料。")
            return

        await self._show_mydata_panel(update, context, target_chat_id)

    async def nearby_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        chat = update.effective_chat
        user = update.effective_user
        db: Database = context.application.bot_data["db"]

        if chat.type in ("group", "supergroup"):
            target_chat_id = chat.id
            await self._bind_group_context(db, chat, user)
        else:
            target_chat_id = await get_user_current_chat(db, user.id)
            if target_chat_id is None:
                await update.effective_message.reply_text("请先在目标群发送 /mydata 绑定群组，再来私聊查看周边。")
                return

        await self._show_nearby_list(update, context, target_chat_id, page=0)

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await callback_handler_action(
            update,
            context,
            start_edit_state_func=self._start_edit_state,
            toggle_visible_func=self._toggle_visible,
            handle_clear_func=self._handle_clear,
            show_mydata_panel_func=self._show_mydata_panel,
            show_nearby_list_func=self._show_nearby_list,
            show_member_detail_func=self._show_member_detail,
            reply_or_edit_func=self._reply_or_edit,
        )

    async def handle_fsm_text_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *, state,
        message_text: str,
    ) -> None:
        await handle_fsm_text_input_action(update, context, session, state=state, message_text=message_text)

    async def handle_fsm_location_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *, state,
    ) -> None:
        await handle_fsm_location_input_action(update, context, session, state=state)

    async def _show_mydata_panel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        await show_mydata_panel(update, context, target_chat_id)

    async def _show_nearby_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, page: int,
    ) -> None:
        await show_nearby_list(update, context, target_chat_id, page=page)

    async def _show_member_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, target_user_id: int,
        back_page: int,
    ) -> None:
        await show_member_detail(update, context, target_chat_id, target_user_id=target_user_id, back_page=back_page)

    async def _start_edit_state(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        *, target_chat_id: int,
        field: str,
    ) -> None:
        await start_edit_state_action(
            update,
            context,
            db,
            target_chat_id=target_chat_id,
            field=field,
            reply_or_edit_func=self._reply_or_edit,
        )

    async def _toggle_visible(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        *, target_chat_id: int,
    ) -> None:
        await toggle_visible_action(
            update,
            context,
            db,
            target_chat_id=target_chat_id,
            show_mydata_panel_func=self._show_mydata_panel,
        )

    async def _handle_clear(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        *, target_chat_id: int,
        step: str,
    ) -> None:
        await handle_clear_action(
            update,
            context,
            db,
            target_chat_id=target_chat_id,
            step=step,
            reply_or_edit_func=self._reply_or_edit,
            show_mydata_panel_func=self._show_mydata_panel,
        )

    async def _reply_or_edit(
        self,
        update: Update,
        text: str,
        reply_markup=None,
        *, parse_mode: str | None = None,
    ) -> None:
        await reply_or_edit(update, text, reply_markup, parse_mode=parse_mode)

    async def _bind_group_context(self, db: Database, chat: Chat, user: User) -> None:
        """确保群与用户存在，并将该群设置为当前管理群。"""
        async with db.session_factory() as session:
            await self._ensure_group_user_context(session, chat, user)
            await session.commit()
        await set_user_current_chat(db, user.id, chat.id)

    async def _ensure_group_user_context(
        self,
        session: AsyncSession,
        chat: Chat,
        user: User,
    ) -> None:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )


_nearby_handler = NearbyHandler()


async def mydata_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = await ensure_command_enabled(context, update, command_key="mydata")
    if not allowed:
        return
    await _nearby_handler.mydata_command(update, context)


async def nearby_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = await ensure_command_enabled(context, update, command_key="nearby")
    if not allowed:
        return
    await _nearby_handler.nearby_command(update, context)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = await ensure_command_enabled(context, update, command_key="list")
    if not allowed:
        return
    await _nearby_handler.nearby_command(update, context)


async def nearby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _nearby_handler.callback_handler(update, context)
