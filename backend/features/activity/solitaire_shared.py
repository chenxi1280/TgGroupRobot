from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.solitaire_service import (
    format_solitaire_message,
    format_solitaire_stats_message,
    get_chat_solitaires,
    get_solitaire_in_chat,
    get_solitaire_stats,
)
from backend.features.activity.ui.solitaire import (
    solitaire_detail_keyboard,
    solitaire_list_keyboard,
    solitaire_menu_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.shared.handlers.base.base_handler import BaseHandler

WAIT_CONFIG = 1
WAIT_DESCRIPTION = 2
WAIT_MAX_PARTICIPANTS = 3
WAIT_POINTS_REQUIRED = 4
WAIT_DEADLINE = 5

log = structlog.get_logger(__name__)


class SolitaireHandler(BaseHandler):
    """接龙 Handler"""

    def __init__(self) -> None:
        super().__init__()
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat_title: str | None = None,
    ) -> None:
        text = f"📋 [{chat_title or target_chat_id}] 接龙管理\n\n管理群内接龙活动"
        await self.message_helper.safe_edit(update, text=text, reply_markup=solitaire_menu_keyboard(target_chat_id))

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            solitaires = await get_chat_solitaires(session, target_chat_id)
            await session.commit()

        if not solitaires:
            await self.message_helper.safe_edit(
                update,
                text="📋 接龙列表\n\n暂无接龙，点击「创建接龙」开始",
                reply_markup=solitaire_menu_keyboard(target_chat_id),
            )
            return

        text = f"📋 接龙列表\n\n共 {len(solitaires)} 个接龙"
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=solitaire_list_keyboard(solitaires, target_chat_id, page),
        )

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_solitaire_stats(session, target_chat_id)
            await session.commit()

        text = format_solitaire_stats_message(stats)
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=solitaire_menu_keyboard(target_chat_id),
        )

    async def show_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        solitaire_id: int,
        target_chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            solitaire = await get_solitaire_in_chat(session, target_chat_id, solitaire_id)
            if not solitaire:
                await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    text="接龙不存在",
                    reply_markup=solitaire_menu_keyboard(target_chat_id),
                )
                return

            text = format_solitaire_message(solitaire, show_closed=False)
            is_active = solitaire.status == SolitaireStatus.active.value
            await session.commit()

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=solitaire_detail_keyboard(solitaire_id, is_active, target_chat_id),
        )


_solitaire_handler = SolitaireHandler()
