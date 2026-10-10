"""统一消息分发器

根据消息来源和用户角色，将消息分发到对应的处理器。

分发规则：
- 私聊消息：优先检查用户状态，有配置状态则走配置流程，否则走默认私聊处理
- 群聊消息：走群聊消息处理器（按优先级处理各功能）
"""
from __future__ import annotations

from typing import Any

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.group_ops.start_handler import private_message_handler as private_default_handler
from backend.platform.db.runtime.session import Database
from backend.platform.runtime.request_scope import bind_request_scope
from backend.platform.state.state_service import get_user_state
from backend.platform.telegram.group_pipeline import GroupMessageHandler
from backend.platform.telegram.message_actor import resolve_message_actor
from backend.platform.telegram.private_config_handler import PrivateConfigHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver

log = structlog.get_logger(__name__)


class MessageDispatcher:
    """统一消息分发器

    根据消息来源（私聊/群聊）和用户状态，将消息分发到对应的处理器。
    """

    def __init__(self) -> None:
        self._private_config_handler = PrivateConfigHandler()
        self._group_message_handler = GroupMessageHandler()

    async def dispatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_message is None:
            return

        chat = update.effective_chat
        message = update.effective_message
        user = resolve_message_actor(update)
        message_text = message.text or message.caption or ""

        log.debug(
            "message_dispatcher_entry",
            chat_id=chat.id,
            user_id=user.id if user is not None else None,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
            chat_type=chat.type,
            message_text_preview=message_text[:50],
        )

        async with bind_request_scope(
            update_id=getattr(update, "update_id", None),
            chat_id=chat.id,
            user_id=user.id if user is not None else None,
        ):
            if chat.type == "private":
                if user is None:
                    return
                await self._dispatch_private(
                    update, context, chat, user=user, message_text=message_text
                )
            else:
                if user is None:
                    return
                await self._group_message_handler.handle(
                    update, context, chat, user=user, message_text=message_text
                )

    async def _dispatch_private(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Any,
        *,
        user: Any,
        message_text: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]

        async with db.session_factory() as session:
            from backend.platform.state.edit_drafts import suspend_conflicting_legacy_inputs
            conflicts = await suspend_conflicting_legacy_inputs(session, user.id)
            if conflicts:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                await session.commit()
                rows = [[InlineKeyboardButton(f"查看群 {target} 的草稿", callback_data=f"draft:list:{target}:0")]
                        for target in sorted({draft.chat_id for draft in conflicts})]
                await update.effective_message.reply_text(
                    "发现多个旧编辑状态，已分别保留为草稿。本条消息未写入配置；请先选择要继续编辑的草稿。",
                    reply_markup=InlineKeyboardMarkup(rows))
                return
            state = await self._get_user_state(
                session=session, db=db, user_id=user.id, chat_id=chat.id
            )

            if state is not None:
                from backend.platform.state.draft_versions import resumed_version_matches
                if not await resumed_version_matches(session, state, lock=True):
                    from backend.platform.state.edit_drafts import archive_state
                    await archive_state(session, state)
                    await session.commit()
                    await update.effective_message.reply_text("正式配置已变化，输入未保存；草稿已保留。请重新打开功能页载入最新配置。")
                    return
                log.debug(
                    "message_dispatcher_private_config",
                    user_id=user.id,
                    state_type=state.state_type,
                )
                await self._private_config_handler.handle(
                    update, context, session, state=state, message_text=message_text
                )
                await session.commit()
                return
            await session.commit()  # Keep TTL reconciliation even when no input remains.

        if not message_text:
            return

        await private_default_handler(update, context)

    async def _get_user_state(self, session: Any, db: Database, user_id: int, *, chat_id: int) -> Any:
        """兼容旧调用方，同时通过新的 scoped state 规则解析状态。"""
        private_state = await get_user_state(session, chat_id=chat_id, user_id=user_id)
        if private_state is not None and private_state.state_type not in {"selected_chat", "guess_draft"}:
            return private_state

        target_chat_id = None
        if private_state is not None and isinstance(private_state.state_data, dict):
            target_chat_id = private_state.state_data.get("managed_chat_id")
        if not target_chat_id:
            target_chat_id = await ChatResolver.get_current_chat(db, user_id)
        if target_chat_id:
            group_state = await get_user_state(session, chat_id=target_chat_id, user_id=user_id)
            return group_state if group_state is not None and group_state.state_type != "guess_draft" else None

        return None
