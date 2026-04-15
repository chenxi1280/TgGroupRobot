"""定时消息任务 Handler。"""
from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import (
    is_clear_command as _is_clear_command,
    parse_buttons_text as _parse_buttons_text,
    resolve_state_chat_id as _resolve_state_chat_id,
    resolve_target_chat_id as _resolve_target_chat_id,
)
from backend.features.automation.scheduled_message_inputs import ScheduledMessageInputMixin
from backend.features.automation.scheduled_message_listing import ScheduledMessageListMixin
from backend.features.automation.scheduled_message_mutations import ScheduledMessageMutationMixin
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.services.permission_service import PermissionPolicyService

log = structlog.get_logger(__name__)


class ScheduledMessageHandler(
    ScheduledMessageListMixin,
    ScheduledMessageMutationMixin,
    ScheduledMessageInputMixin,
    BaseHandler,
):
    """定时消息任务 Handler"""

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

    async def _check_permission(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> bool:
        if update.effective_user is None:
            return False
        return await PermissionPolicyService.can_manage(
            context,
            chat_id,
            update.effective_user.id,
            capability="automation",
        )


_scheduled_message_handler = ScheduledMessageHandler()


async def sm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """定时消息回调处理器"""
    if update.callback_query is None or update.effective_message is None:
        return

    try:
        parser = CallbackParser.parse(update.callback_query.data)
        action = parser.get(1)
        target_chat_id = parser.get_int_optional(2)
        if target_chat_id is None:
            await answer_callback_query_safely(
                update,
                "❌ 群组参数无效，请返回重试",
                show_alert=True,
            )
            return

        if action == "list":
            await _scheduled_message_handler.show_list(update, context, target_chat_id, parser.get_int(3, default=0))
        elif action == "open":
            await _scheduled_message_handler.show_detail(update, context, target_chat_id, parser.get(3))
        elif action == "add":
            await _scheduled_message_handler.create_task(update, context, target_chat_id)
        elif action == "set":
            await _scheduled_message_handler.set_field(
                update,
                context,
                target_chat_id,
                parser.get(3),
                parser.get(4),
                parser.get(5),
            )
        elif action == "edit":
            await _scheduled_message_handler.edit_field(
                update,
                context,
                target_chat_id,
                parser.get(3),
                parser.get(4),
            )
        elif action == "preview":
            await _scheduled_message_handler.preview_task(update, context, target_chat_id, parser.get(3))
        elif action == "del_confirm":
            await _scheduled_message_handler.confirm_delete(update, context, target_chat_id, parser.get(3))
        elif action == "del_do":
            await _scheduled_message_handler.delete_task(update, context, target_chat_id, parser.get(3))
        elif action == "del_cancel":
            await _scheduled_message_handler.cancel_delete(update, context, target_chat_id, parser.get(3))
        else:
            await update.callback_query.answer(text="❌ 未知的操作", show_alert=True)
    except Exception as exc:
        log.error("处理定时消息回调失败", error=str(exc), callback_data=update.callback_query.data)
        await answer_callback_query_safely(
            update,
            f"❌ 操作失败: {build_public_error_text(exc, fallback='内部错误')}",
            show_alert=True,
        )
