"""定时消息任务路由器

提供定时消息任务功能的所有路由注册。
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from bot.handlers.scheduled_message_handler import sm_callback_handler, _scheduled_message_handler
from bot.routers.base import BaseRouter
from bot.services.state.state_service import get_user_state

log = structlog.get_logger(__name__)


class ScheduledMessageRouter(BaseRouter):
    """定时消息任务功能路由器"""

    @property
    def name(self) -> str:
        return "scheduled_message"

    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")

        # 回调处理器（使用前缀匹配）
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:list:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:add:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:open:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:set:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:edit:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:del_confirm:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:del_do:"))
        app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=r"^sm:del_cancel:"))

        # 无操作按钮处理器（用于提示按钮等）
        async def handle_noop(update: Update, context) -> None:
            """处理无操作按钮"""
            if update.callback_query:
                await update.callback_query.answer()

        app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^_noop$"))

        # FSM 消息处理器（处理文本输入）
        async def handle_fsm_text_input(update: Update, context) -> None:
            """处理 FSM 状态下的文本输入"""
            # 添加调试日志
            log.warning(
                "=== SCHEDULED_MESSAGE TEXT HANDLER CALLED ===",
                user_id=update.effective_user.id if update.effective_user else None,
                chat_id=update.effective_chat.id if update.effective_chat else None,
                text_preview=(update.effective_message.text or "")[:50] if update.effective_message else "",
            )

            if update.effective_message is None or update.effective_user is None:
                return

            # 确定目标群组 ID
            if update.effective_chat.type == "private":
                # 私聊：从状态中获取目标群组 ID
                db = context.application.bot_data["db"]
                async with db.session_factory() as session:
                    # 尝试从状态中获取
                    from bot.models.enums import ConversationStateType
                    state_types = [
                        ConversationStateType.sm_edit_text,
                        ConversationStateType.sm_edit_buttons,
                        ConversationStateType.sm_edit_start_at,
                        ConversationStateType.sm_edit_end_at,
                    ]

                    state = await get_user_state(
                        session,
                        update.effective_chat.id,
                        update.effective_user.id,
                    )

                    if not state or state.state_type not in state_types:
                        log.info("scheduled_message_state_not_match", state_type=state.state_type if state else None)
                        return

                    # 从 state_data 中获取目标群组 ID
                    log.info("scheduled_message_state_matched", state_type=state.state_type)
                    target_chat_id = state.state_data.get("target_chat_id")
                    if not target_chat_id:
                        # 兼容旧逻辑：如果 state_data 中没有 target_chat_id，使用 state.chat_id
                        target_chat_id = state.chat_id

                target_user_id = update.effective_user.id
            else:
                # 群聊
                target_chat_id = update.effective_chat.id
                target_user_id = update.effective_user.id

            log.info("scheduled_message_calling_handler", target_chat_id=target_chat_id)
            await _scheduled_message_handler.handle_fsm_input(
                update, context, target_chat_id, target_user_id, update.effective_message.text
            )

        # FSM 媒体处理器（处理图片、视频等）
        async def handle_fsm_media_input(update: Update, context) -> None:
            """处理 FSM 状态下的媒体输入"""
            # 添加调试日志
            log.warning(
                "=== SCHEDULED_MESSAGE MEDIA HANDLER CALLED ===",
                user_id=update.effective_user.id if update.effective_user else None,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )

            if update.effective_message is None or update.effective_user is None:
                return

            # 确定目标群组 ID
            if update.effective_chat.type == "private":
                # 私聊：从状态中获取目标群组 ID
                db = context.application.bot_data["db"]
                async with db.session_factory() as session:
                    from bot.models.enums import ConversationStateType
                    state = await get_user_state(
                        session,
                        update.effective_chat.id,
                        update.effective_user.id,
                    )

                    if not state or state.state_type != ConversationStateType.sm_edit_media:
                        return

                    # 从 state_data 中获取目标群组 ID
                    target_chat_id = state.state_data.get("target_chat_id")
                    if not target_chat_id:
                        # 兼容旧逻辑：如果 state_data 中没有 target_chat_id，使用 state.chat_id
                        target_chat_id = state.chat_id

                target_user_id = update.effective_user.id
            else:
                # 群聊
                target_chat_id = update.effective_chat.id
                target_user_id = update.effective_user.id

            await _scheduled_message_handler.handle_media_input(
                update, context, target_chat_id, target_user_id
            )

        # 注意：配置消息已被 MessageDispatcher 的 PrivateConfigHandler 统一处理
        # 这些 MessageHandler 已移除，避免重复处理
        #
        # # 注册消息处理器（低优先级，放在 group=1 以避免冲突）
        # # 文本输入处理器
        # app.add_handler(
        #     MessageHandler(
        #         filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        #         handle_fsm_text_input,
        #     ),
        #     group=1,
        # )
        #
        # # 媒体输入处理器
        # app.add_handler(
        #     MessageHandler(
        #         filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.Sticker.ALL | filters.ANIMATION),
        #         handle_fsm_media_input,
        #     ),
        #     group=1,
        # )

        log.info(f"{self.name} router registered successfully")
