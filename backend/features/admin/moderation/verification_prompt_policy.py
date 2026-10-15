"""验证提示失败策略（fail-open / fail-closed）切换。"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_config_service import (
    update_module_config,
    verification_prompt_fail_open,
)


async def toggle_prompt_fail_open(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    db: Database,
    show_menu,
) -> None:
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.refresh(settings, with_for_update=True)
        current = verification_prompt_fail_open(settings)
        await update_module_config(
            session,
            settings,
            module="verification",
            patch={"prompt_fail_open": not current},
        )
        await session.commit()
        next_label = "放行(fail-open)" if not current else "保持限制(fail-closed)"
    await answer_callback_query_safely(update, f"已切换为：{next_label}")
    await show_menu(update, context, chat_id)
