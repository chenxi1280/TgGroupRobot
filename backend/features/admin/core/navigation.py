from __future__ import annotations

from backend.shared.callback_parser import CallbackData
from backend.shared.ui.menu_layout import page_slice, page_navigation

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
        chats = [item for item in chats if item[0] != target_chat_id]
        callback = CallbackParser.parse(update.callback_query.data or "")
        chats, total, page = page_slice(chats, callback.get_int_optional(4) or 0)
        operation, pick = ("source", "pick_source") if mode == "import" else ("target", "pick_target")
        rows = [[InlineKeyboardButton(f"{title[:22]} · {chat_id}",
                                      callback_data=f"adm:{mode}:{target_chat_id}:{operation}:{chat_id}")]
                for chat_id, title, _ in chats]
        rows.extend(page_navigation(page, total, lambda value: f"adm:{mode}:{target_chat_id}:{pick}:{value}"))
        rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:{mode}:{target_chat_id}")])
        return InlineKeyboardMarkup(rows)

    async def _handle_switch_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int | None = None,
        *, callback_data: CallbackData | None = None,
    ) -> None:
        """处理切换群组操作"""
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)

        page = callback_data.get_int_optional(2) if callback_data else 0
        await self._show_group_selection(update, chats, current_chat_id, page=page or 0)

    async def _handle_select_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData | None = None,
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
        *, callback_data: CallbackData | None = None,
    ) -> None:
        """处理返回主菜单操作"""
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        if current_chat_id not in {item[0] for item in chats}:
            await self._show_group_selection(update, chats, None)
            return
        await self._show_main_menu(update, context, current_chat_id)

    async def _handle_back_to_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackData | None = None,
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
        from backend.platform.telegram.ui_feedback import show_pending_feedback
        await show_pending_feedback(update, context)
        db: Database = context.application.bot_data["db"]
        chat_title = await self._get_chat_title(db, chat_id)
        from backend.features.group_ops.services.group_daily_stats import get_admin_menu_stats

        async with db.session_factory() as session:
            menu_stats = await get_admin_menu_stats(session, chat_id)
            await session.commit()

        text = format_admin_main_menu_text(chat_title, menu_stats) + "\n管理资格：可配置"
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
        """旧群设置入口兼容到系统管理。"""
        await self._show_category_menu(update, context, chat_id, category="system")

    async def _show_category_safety(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="safety")

    async def _show_category_messages(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="messages")

    async def _show_category_growth(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="growth")

    async def _show_category_activities(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="activities")

    async def _show_category_garage(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="garage")

    async def _show_category_system(self, update, context, chat_id: int) -> None:
        await self._show_category_menu(update, context, chat_id, category="system")

    async def _show_category_menu(self, update, context, chat_id: int, *, category: str) -> None:
        from backend.features.admin.ui.admin_main_keyboards import ADMIN_CATEGORIES, admin_category_menu
        title = await self._get_chat_title(context.application.bot_data["db"], chat_id)
        label = ADMIN_CATEGORIES[category][0]
        await self.message_helper.safe_edit(
            update, text=f"当前群：{title}\n管理资格：可配置\n\n{label}",
            reply_markup=admin_category_menu(category, chat_id),
        )

    async def _show_group_selection(
        self,
        update: Update,
        managed_chats: list,
        current_chat_id: int | None,
        *, page: int = 0,
    ) -> None:
        """显示群组选择列表"""
        page = max(0, min(page, max(0, (len(managed_chats) - 1) // 8)))
        keyboard = create_group_selection_keyboard(managed_chats, current_chat_id, page)
        text = (f"选择要管理的群组：共 {len(managed_chats)} 个，"
                f"第 {page + 1}/{max(1, (len(managed_chats) + 7) // 8)} 页")
        if not managed_chats:
            text = "暂无可管理群组。请将机器人添加到群中并设为管理员，然后刷新。"

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard,
        )
