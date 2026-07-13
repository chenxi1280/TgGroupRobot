"""定时消息任务 Handler。"""
from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import (
    is_clear_command as _is_clear_command,  # noqa: F401 - compatibility export
    parse_buttons_text as _parse_buttons_text,  # noqa: F401 - compatibility export
    resolve_state_chat_id as _resolve_state_chat_id,  # noqa: F401 - compatibility export
    resolve_target_chat_id as _resolve_target_chat_id,  # noqa: F401 - compatibility export
)
from backend.features.automation.scheduled_message_inputs import ScheduledMessageInputMixin
from backend.features.automation.scheduled_message_listing import ScheduledMessageListMixin
from backend.features.automation.scheduled_message_mutations import ScheduledMessageMutationMixin
from backend.features.automation.scheduled_message_operations import ScheduledMessageOperationsMixin
from backend.platform.state.conversation_state_service import ConversationStateService  # noqa: F401 - test patch point
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.services.permission_service import PermissionPolicyService

log = structlog.get_logger(__name__)


class ScheduledMessageHandler(
    ScheduledMessageListMixin,
    ScheduledMessageMutationMixin,
    ScheduledMessageInputMixin,
    ScheduledMessageOperationsMixin,
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


async def _dispatch_scheduled_view_action(
    update, context, *, action: str, chat_id: int, parser
) -> bool:
    handler = _scheduled_message_handler
    if action == "list":
        await handler.show_list(
            update, context, chat_id, page=parser.get_int(3, default=0)
        )
        return True
    if action == "open":
        await handler.show_detail(update, context, chat_id, parser.get(3))
        return True
    if action == "add":
        await handler.create_task(update, context, chat_id)
        return True
    if action == "set":
        await handler.set_field(
            update, context, chat_id, task_id=parser.get(3),
            field=parser.get(4), value=parser.get(5),
        )
        return True
    if action == "edit":
        await handler.edit_field(
            update, context, chat_id, task_id=parser.get(3), field=parser.get(4)
        )
        return True
    if action == "preview":
        await handler.preview_task(
            update, context, chat_id, task_id=parser.get(3)
        )
        return True
    if action != "history":
        return False
    await handler.show_occurrence_history(
        update, context, chat_id, task_key=parser.get(3)
    )
    return True


async def _dispatch_scheduled_occurrence_action(
    update, context, *, action: str, chat_id: int, parser
) -> bool:
    occurrence_actions = {
        "occ_retry": "retry",
        "occ_cancel": "cancel",
        "occ_replay_do": "replay",
    }
    operation = occurrence_actions.get(action)
    if operation is not None:
        await _scheduled_message_handler.operate_occurrence(
            update, context, chat_id=chat_id,
            occurrence_id=parser.get_int(3), action=operation,
        )
        return True
    if action != "occ_replay_confirm":
        return False
    await _scheduled_message_handler.confirm_uncertain_replay(
        update, context, chat_id=chat_id, occurrence_id=parser.get_int(3)
    )
    return True


async def _dispatch_scheduled_delete_action(
    update, context, *, action: str, chat_id: int, parser
) -> bool:
    handlers = {
        "del_confirm": _scheduled_message_handler.confirm_delete,
        "del_do": _scheduled_message_handler.delete_task,
        "del_cancel": _scheduled_message_handler.cancel_delete,
    }
    handler = handlers.get(action)
    if handler is None:
        return False
    await handler(update, context, chat_id, task_id=parser.get(3))
    return True


async def _dispatch_scheduled_callback(update, context, *, parser, chat_id: int) -> None:
    action = parser.get(1)
    if await _dispatch_scheduled_view_action(
        update, context, action=action, chat_id=chat_id, parser=parser
    ):
        return
    if await _dispatch_scheduled_occurrence_action(
        update, context, action=action, chat_id=chat_id, parser=parser
    ):
        return
    if await _dispatch_scheduled_delete_action(
        update, context, action=action, chat_id=chat_id, parser=parser
    ):
        return
    await update.callback_query.answer(text="❌ 未知的操作", show_alert=True)


async def sm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """定时消息回调处理器"""
    if update.callback_query is None or update.effective_message is None:
        return

    try:
        parser = CallbackParser.parse(update.callback_query.data)
        target_chat_id = parser.get_int_optional(2)
        if target_chat_id is None:
            await answer_callback_query_safely(
                update,
                "❌ 群组参数无效，请返回重试",
                show_alert=True,
            )
            return

        await _dispatch_scheduled_callback(
            update, context, parser=parser, chat_id=target_chat_id
        )
    except Exception as exc:
        log.error("处理定时消息回调失败", error=str(exc), callback_data=update.callback_query.data)
        await answer_callback_query_safely(
            update,
            f"❌ 操作失败: {build_public_error_text(exc, fallback='内部错误')}",
            show_alert=True,
        )
