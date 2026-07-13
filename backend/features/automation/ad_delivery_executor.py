from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

import structlog
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from backend.platform.delivery import DeliveryOutcome
from backend.shared.async_tasks import spawn_background_task
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class AdDeliveryPlan:
    history_id: int
    chat_id: int
    campaign_id: int
    content_snapshot: dict[str, Any]
    rule_snapshot: dict[str, Any]


class AdDeliveryExecutor(Protocol):
    async def execute(self, plan: AdDeliveryPlan) -> DeliveryOutcome: ...


class TelegramAdDeliveryExecutor:
    def __init__(self, app) -> None:
        self._app = app
        self._context = SimpleNamespace(bot=app.bot, application=app)

    async def execute(self, plan: AdDeliveryPlan) -> DeliveryOutcome:
        await self._apply_pre_send_actions(plan)
        try:
            result = await self._send(plan)
        except RetryAfter as exc:
            return DeliveryOutcome.retryable_failure("telegram_retry_after", str(exc))
        except (Forbidden, BadRequest) as exc:
            return DeliveryOutcome.permanent_failure(_error_code(exc), str(exc))
        except NetworkError as exc:
            return DeliveryOutcome.uncertain("telegram_network_unknown", str(exc))
        except TelegramError as exc:
            return DeliveryOutcome.uncertain("telegram_result_unknown", str(exc))
        pinned_id = await self._pin_if_requested(plan, int(result.message_id))
        self._schedule_delete_if_requested(plan, int(result.message_id))
        return DeliveryOutcome.success(
            message_id=int(result.message_id),
            metadata={"pinned_message_id": pinned_id},
        )

    async def _apply_pre_send_actions(self, plan: AdDeliveryPlan) -> None:
        rule = plan.rule_snapshot
        content = plan.content_snapshot
        if rule["delete_policy"] == "delete_prev":
            await self._best_effort("delete", plan.chat_id, rule.get("last_sent_message_id"))
        elif rule["delete_policy"] == "delete_prev_cycle":
            await self._best_effort("delete", plan.chat_id, content.get("last_sent_message_id"))
        if rule["mode"] == "send_pin" and rule["unpin_previous"]:
            await self._best_effort("unpin", plan.chat_id, rule.get("last_pinned_message_id"))

    async def _best_effort(self, action: str, chat_id: int, message_id: int | None) -> None:
        if not message_id:
            return
        method = PublishService.delete if action == "delete" else PublishService.unpin
        try:
            await method(self._context, chat_id=chat_id, message_id=message_id)
        except TelegramError as exc:
            log.warning("ad_rotation_pre_action_failed", action=action, chat_id=chat_id, error=str(exc))

    async def _send(self, plan: AdDeliveryPlan):
        content = plan.content_snapshot
        text = str(content.get("content") or "").strip() or str(content.get("title") or "")
        markup = _restore_markup(content.get("buttons"), self._app.bot)
        if content.get("image_file_id"):
            return await PublishService.send_photo(
                self._context,
                chat_id=plan.chat_id,
                photo=content["image_file_id"],
                caption=text,
                reply_markup=markup,
            )
        return await PublishService.send(self._context, chat_id=plan.chat_id, text=text, reply_markup=markup)

    async def _pin_if_requested(self, plan: AdDeliveryPlan, message_id: int) -> int | None:
        if plan.rule_snapshot["mode"] != "send_pin":
            return None
        try:
            await PublishService.pin(self._context, chat_id=plan.chat_id, message_id=message_id)
        except TelegramError as exc:
            log.warning("ad_rotation_pin_failed", history_id=plan.history_id, error=str(exc))
            return None
        return message_id

    def _schedule_delete_if_requested(self, plan: AdDeliveryPlan, message_id: int) -> None:
        if plan.rule_snapshot["delete_policy"] != "delete_delay":
            return
        from backend.features.automation.ad_delivery_cleanup import delete_later

        spawn_background_task(
            self._app,
            delete_later(
                self._context,
                chat_id=plan.chat_id,
                message_id=message_id,
                delay_seconds=int(plan.rule_snapshot["delete_delay_seconds"]),
            ),
            name="ad_rotation.delete_later",
        )


def _restore_markup(buttons: object, bot):
    if not buttons:
        return None
    return InlineKeyboardMarkup.de_json({"inline_keyboard": buttons}, bot)


def _error_code(error: TelegramError) -> str:
    return "telegram_forbidden" if isinstance(error, Forbidden) else "telegram_bad_request"
