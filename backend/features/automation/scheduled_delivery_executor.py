from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

import structlog
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from backend.platform.delivery import DeliveryOutcome
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)
_MEDIA_SENDERS = {
    "photo": (PublishService.send_photo, "photo"),
    "video": (PublishService.send_video, "video"),
    "document": (PublishService.send_document, "document"),
    "animation": (PublishService.send_animation, "animation"),
    "sticker": (PublishService.send_sticker, "sticker"),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduledDeliveryPlan:
    occurrence_id: int
    task_id: str
    chat_id: int
    snapshot: dict[str, Any]


class ScheduledDeliveryExecutor(Protocol):
    async def execute(self, plan: ScheduledDeliveryPlan) -> DeliveryOutcome: ...


class TelegramScheduledDeliveryExecutor:
    def __init__(self, app) -> None:
        self._app = app
        self._context = SimpleNamespace(bot=app.bot, application=app)

    async def execute(self, plan: ScheduledDeliveryPlan) -> DeliveryOutcome:
        await self._delete_previous(plan)
        try:
            result = await self._send(plan)
        except RetryAfter as exc:
            return DeliveryOutcome.retryable_failure("telegram_retry_after", str(exc))
        except (Forbidden, BadRequest) as exc:
            return DeliveryOutcome.permanent_failure(_telegram_error_code(exc), str(exc))
        except NetworkError as exc:
            return DeliveryOutcome.uncertain("telegram_network_unknown", str(exc))
        except TelegramError as exc:
            return DeliveryOutcome.uncertain("telegram_result_unknown", str(exc))
        await self._pin(plan, int(result.message_id))
        return DeliveryOutcome.success(message_id=int(result.message_id))

    async def _delete_previous(self, plan: ScheduledDeliveryPlan) -> None:
        previous_id = plan.snapshot.get("last_sent_message_id")
        if not plan.snapshot.get("delete_previous") or not previous_id:
            return
        try:
            await PublishService.delete(self._context, chat_id=plan.chat_id, message_id=previous_id)
        except TelegramError as exc:
            log.warning("scheduled_message_delete_previous_failed", occurrence_id=plan.occurrence_id, error=str(exc))

    async def _pin(self, plan: ScheduledDeliveryPlan, message_id: int) -> None:
        if not plan.snapshot.get("pin_message"):
            return
        try:
            await PublishService.pin(self._context, chat_id=plan.chat_id, message_id=message_id)
        except TelegramError as exc:
            log.warning("scheduled_message_pin_failed", occurrence_id=plan.occurrence_id, error=str(exc))

    async def _send(self, plan: ScheduledDeliveryPlan):
        snapshot = plan.snapshot
        method, payload = _build_publish_call(snapshot)
        return await method(
            self._context,
            chat_id=plan.chat_id,
            reply_markup=_restore_markup(snapshot.get("buttons"), self._app.bot),
            **payload,
        )


def _build_publish_call(snapshot: dict[str, Any]):
    parse_mode = snapshot.get("parse_mode")
    common = {"parse_mode": None if parse_mode == "none" else parse_mode}
    media_type = snapshot.get("media_type")
    file_id = snapshot.get("media_file_id")
    text = snapshot.get("text")
    if media_type in _MEDIA_SENDERS and file_id:
        method, field = _MEDIA_SENDERS[media_type]
        payload = {field: file_id}
        if media_type != "sticker":
            payload.update({"caption": text, **common})
        return method, payload
    if str(text or "").strip():
        return PublishService.send, {"text": text, **common}
    raise ValueError("scheduled message snapshot has no sendable content")


def _restore_markup(buttons: object, bot):
    if not buttons:
        return None
    return InlineKeyboardMarkup.de_json({"inline_keyboard": buttons}, bot)


def _telegram_error_code(error: TelegramError) -> str:
    return "telegram_forbidden" if isinstance(error, Forbidden) else "telegram_bad_request"
