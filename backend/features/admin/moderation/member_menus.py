from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.moderation.member_menu_views import (
    build_force_subscribe_view,
    build_new_member_limit_view,
    build_night_mode_view,
    force_subscribe_keyboard,
    force_subscribe_text,
    new_member_limit_keyboard,
    new_member_limit_text,
    night_mode_keyboard,
    night_mode_text,
)
from backend.platform.db.runtime.session import Database


async def _load_member_settings(owner, update, context, *, chat_id: int):
    from backend.features.admin import admin_handler

    db: Database = context.application.bot_data["db"]
    await owner._set_current_chat(db, update.effective_user.id, chat_id)
    async with db.session_factory() as session:
        settings = await admin_handler.get_chat_settings(session, chat_id)
        await session.commit()
        return settings


class ModerationMemberMenusMixin:
    async def _show_force_subscribe_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        settings = await _load_member_settings(self, update, context, chat_id=chat_id)
        view = await build_force_subscribe_view(context, settings, chat_id)
        await self.message_helper.safe_edit(
            update,
            text=force_subscribe_text(view),
            reply_markup=force_subscribe_keyboard(view),
        )

    async def _show_new_member_limit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        settings = await _load_member_settings(self, update, context, chat_id=chat_id)
        view = build_new_member_limit_view(settings, chat_id)
        await self.message_helper.safe_edit(
            update,
            text=new_member_limit_text(view),
            reply_markup=new_member_limit_keyboard(view),
        )

    async def _show_night_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        settings = await _load_member_settings(self, update, context, chat_id=chat_id)
        view = build_night_mode_view(settings, chat_id)
        await self.message_helper.safe_edit(
            update,
            text=night_mode_text(view),
            reply_markup=night_mode_keyboard(view),
        )
