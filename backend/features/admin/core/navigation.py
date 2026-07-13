from __future__ import annotations

from backend.features.admin.support import *


class CoreNavigationMixin:
    async def _build_import_source_keyboard(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        target_chat_id: int,
        mode: str,
    ) -> InlineKeyboardMarkup:
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        rows: list[list[InlineKeyboardButton]] = []
        for chat_id, title, _ in chats:
            if mode == "import":
                rows.append([InlineKeyboardButton(f"{title}", callback_data=f"adm:import:{target_chat_id}:source:{chat_id}")])
            else:
                if chat_id == target_chat_id:
                    continue
                rows.append([InlineKeyboardButton(f"{title}", callback_data=f"adm:clone:{target_chat_id}:target:{chat_id}")])
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{mode}:{target_chat_id}")])
        return InlineKeyboardMarkup(rows)

    async def _handle_switch_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int | None = None,
        *, callback_data: CallbackParser | None = None,
    ) -> None:
        """处理切换群组操作"""
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)

        await self._show_group_selection(update, chats, current_chat_id)

    async def _handle_select_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser | None = None,
    ) -> None:
        """处理选择群组操作"""
        db: Database = context.application.bot_data["db"]
        await set_user_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _handle_back_to_main(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int | None = None,
        *, callback_data: CallbackParser | None = None,
    ) -> None:
        """处理返回主菜单操作"""
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
        await self._show_main_menu(update, context, current_chat_id)

    async def _handle_back_to_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser | None = None,
    ) -> None:
        """处理返回指定群组菜单操作"""
        await self._show_main_menu(update, context, chat_id)

    async def _get_chat_title(self, db: Database, chat_id: int) -> str:
        """获取群组标题（优先从 Telegram API 实时获取）"""
        from backend.platform.db.schema.models.core import TgChat
        from sqlalchemy import select

        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == chat_id)
            chat_result = await session.execute(chat_stmt)
            chat = chat_result.scalar_one_or_none()
            db_title = chat.title if chat else None

        if db_title:
            return db_title

        try:
            tg_chat = await self.message_helper._bot.get_chat(chat_id)
            return tg_chat.title or f"群组{chat_id}"
        except (TelegramError, AttributeError, Exception) as exc:
            log.warning(
                "admin_chat_title_lookup_failed",
                chat_id=chat_id,
                db_title=db_title,
                error=str(exc),
            )
            return db_title or f"群组{chat_id}"

    async def _set_current_chat(
        self,
        db: Database,
        user_id: int,
        chat_id: int,
    ) -> None:
        """设置当前管理的群组"""
        await set_user_current_chat(db, user_id, chat_id)

    async def _show_main_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示主菜单"""
        db: Database = context.application.bot_data["db"]
        chat_title = await self._get_chat_title(db, chat_id)
        from backend.features.group_ops.services.group_daily_stats import get_admin_menu_stats

        async with db.session_factory() as session:
            menu_stats = await get_admin_menu_stats(session, chat_id)
            await session.commit()

        text = format_admin_main_menu_text(chat_title, menu_stats)
        keyboard = admin_main_menu(chat_id)

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard,
        )

    async def _show_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示设置菜单（已整合到主菜单）"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _show_group_selection(
        self,
        update: Update,
        managed_chats: list,
        current_chat_id: int | None,
    ) -> None:
        """显示群组选择列表"""
        keyboard = create_group_selection_keyboard(managed_chats, current_chat_id)
        text = "🔄 选择要管理的群组："

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard,
        )
