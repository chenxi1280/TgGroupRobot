"""群聊消息处理器

按优先级处理群聊消息：
1. 核心功能层（群控、强制关注、违禁词、自动回复）
2. 业务功能层（验证优先，然后抽奖、接龙、审核）
3. 发言积分作为旁路：默认发放，仅在明确 suppress 时跳过
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Awaitable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.runtime.request_scope import (
    mark_suppress_message_points,
    should_award_message_points,
)
from backend.shared.errors import BusinessRuleError

log = structlog.get_logger(__name__)

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """业务 handler 结果：消费消息与是否抑制发言积分解耦。"""

    consumed: bool = False
    suppress_points: bool = False

    @classmethod
    def from_raw(cls, result: Any) -> "HandlerResult":
        if isinstance(result, HandlerResult):
            return result
        if result is True:
            return cls(consumed=True, suppress_points=False)
        return cls(consumed=False, suppress_points=False)


class GroupMessageHandler:
    """群聊消息处理器。"""

    def __init__(self) -> None:
        self._core_handler: HandlerFunc | None = None
        self._business_handlers: list[tuple[str, HandlerFunc]] | None = None
        self._points_handler: HandlerFunc | None = None

    def _get_core_handler(self) -> HandlerFunc:
        if self._core_handler is None:
            from backend.features.group_ops.group_message_handler import unified_group_message_handler

            self._core_handler = unified_group_message_handler
        return self._core_handler

    def _get_business_handlers(self) -> list[tuple[str, HandlerFunc]]:
        if self._business_handlers is None:
            from backend.features.activity.auction_handler import auction_group_message_handler
            from backend.features.activity.engagement_handler import engagement_message_handler
            from backend.features.activity.game_handler import game_message_handler
            from backend.features.activity.guess_handler import guess_message_handler
            from backend.features.activity.lottery_handler import lottery_message_handler
            from backend.features.activity.solitaire_handler import solitaire_join_message_handler
            from backend.features.moderation.moderation_handler import moderation_message_handler
            from backend.features.verification.verification_handler import verify_message_handler

            self._business_handlers = [
                ("verification", verify_message_handler),
                ("auction", auction_group_message_handler),
                ("engagement", engagement_message_handler),
                ("game", game_message_handler),
                ("guess", guess_message_handler),
                ("lottery", lottery_message_handler),
                ("solitaire", solitaire_join_message_handler),
                ("moderation", moderation_message_handler),
            ]
        return self._business_handlers

    def _get_points_handler(self) -> HandlerFunc:
        if self._points_handler is None:
            from backend.features.points.points_handler import message_points_handler

            self._points_handler = message_points_handler
        return self._points_handler

    async def handle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Any,
        *,
        user: Any,
        message_text: str,
    ) -> bool:
        log.debug(
            "group_message_handler_entry",
            chat_id=chat.id,
            user_id=user.id,
            message_text_preview=message_text[:50],
        )
        if await self._run_core(update, context, chat=chat, user=user):
            return True
        await self._run_business_chain(update, context, chat=chat, user=user)
        await self._maybe_award_points(update, context, user=user)
        return False

    async def _run_core(self, update, context, *, chat, user) -> bool:
        core_result = await self._safe_execute(
            self._get_core_handler(),
            update,
            context,
            handler_name="core",
            default_suppress_on_consume=True,
        )
        if not core_result.consumed:
            return False
        mark_suppress_message_points(True)
        log.debug("group_message_handler_short_circuited", chat_id=chat.id, user_id=user.id)
        return True

    async def _run_business_chain(self, update, context, *, chat, user) -> None:
        for name, handler in self._get_business_handlers():
            result = await self._safe_execute(
                handler,
                update,
                context,
                handler_name=name,
                default_suppress_on_consume=False,
            )
            if result.suppress_points:
                mark_suppress_message_points(True)
            if result.consumed:
                log.debug(
                    "group_business_handler_consumed",
                    chat_id=chat.id,
                    user_id=user.id,
                    handler=name,
                    suppress_points=result.suppress_points,
                )
                return

    async def _maybe_award_points(self, update, context, *, user) -> None:
        if not should_award_message_points():
            log.debug("group_message_points_suppressed", user_id=getattr(user, "id", None))
            return
        await self._safe_execute(
            self._get_points_handler(),
            update,
            context,
            handler_name="points",
            default_suppress_on_consume=False,
        )

    async def _safe_execute(
        self,
        handler: HandlerFunc,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        handler_name: str,
        default_suppress_on_consume: bool,
    ) -> HandlerResult:
        try:
            raw = await handler(update, context)
            result = HandlerResult.from_raw(raw)
            if result.consumed and default_suppress_on_consume and not result.suppress_points:
                return HandlerResult(consumed=True, suppress_points=True)
            return result
        except BusinessRuleError as exc:
            log.warning(
                "group_handler_business_error",
                handler=handler_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            log.exception(
                "group_handler_failed",
                handler=handler_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise
        return HandlerResult()
