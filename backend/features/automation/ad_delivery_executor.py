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


@dataclass(frozen=True, slots=True, kw_only=True)
class AdDeliveryPlan:
    history_id: int
    chat_id: int
    campaign_id: int
    content_snapshot: dict[str, Any]
    rule_snapshot: dict[str, Any]
    attempt_count: int | None = None


class AdDeliveryExecutor(Protocol):
    async def execute(self, plan: AdDeliveryPlan) -> DeliveryOutcome: ...


class TelegramAdDeliveryExecutor:
    def __init__(self, app) -> None:
        self._app = app
        self._context = SimpleNamespace(bot=app.bot, application=app)

    async def execute(self, plan: AdDeliveryPlan) -> DeliveryOutcome:
        actions = await self._apply_pre_send_actions(plan)
        try:
            result = await self._send(plan)
        except RetryAfter as exc:
            return DeliveryOutcome.retryable_failure("telegram_retry_after", str(exc),metadata={'post_actions':actions})
        except (Forbidden, BadRequest) as exc:
            return DeliveryOutcome.permanent_failure(_error_code(exc), str(exc),metadata={'post_actions':actions})
        except NetworkError as exc:
            return DeliveryOutcome.uncertain("telegram_network_unknown", str(exc),metadata={'post_actions':actions})
        except TelegramError as exc:
            return DeliveryOutcome.uncertain("telegram_result_unknown", str(exc),metadata={'post_actions':actions})
        from backend.features.automation.delivery_action_journal import record_receipt
        await record_receipt(self._app,plan,message_id=int(result.message_id))
        pinned_id,actions['pin'] = await self._pin_if_requested(plan, int(result.message_id))
        return DeliveryOutcome.success(
            message_id=int(result.message_id),
            metadata={"pinned_message_id": pinned_id, "post_actions": actions},
        )

    async def _apply_pre_send_actions(self, plan: AdDeliveryPlan) -> dict[str, str]:
        rule = plan.rule_snapshot
        content = plan.content_snapshot
        actions = {"delete_previous": "not_requested", "unpin_previous": "not_requested"}
        if rule["delete_policy"] == "delete_prev":
            actions["delete_previous"] = await self._best_effort("delete", plan, rule.get("last_sent_message_id"))
        elif rule["delete_policy"] == "delete_prev_cycle":
            actions["delete_previous"] = await self._best_effort("delete", plan, content.get("last_sent_message_id"))
        if rule["mode"] == "send_pin" and rule["unpin_previous"]:
            actions["unpin_previous"] = await self._best_effort("unpin", plan, rule.get("last_pinned_message_id"))
        return actions

    async def _best_effort(self, action: str, plan, message_id: int | None) -> str:
        if not message_id:
            return "not_requested"
        from backend.features.automation.delivery_action_journal import run_action
        try:
            return await run_action(self._app,plan,action='delete_previous' if action=='delete' else 'unpin_previous',message_id=message_id)
        except TelegramError as exc:
            log.warning("ad_rotation_pre_action_failed", action=action, chat_id=plan.chat_id, error=str(exc))
            return "failed"
        return "succeeded"

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

    async def _pin_if_requested(self, plan: AdDeliveryPlan, message_id: int) -> tuple[int | None,str]:
        if plan.rule_snapshot["mode"] != "send_pin":
            return None,'not_requested'
        from backend.features.automation.delivery_action_journal import run_action
        try:
            status=await run_action(self._app,plan,action='pin',message_id=message_id)
        except (BadRequest,Forbidden):
            return None,'failed'
        except Exception as exc:
            log.warning("ad_rotation_pin_failed", history_id=plan.history_id, error=str(exc))
            return None,'uncertain'
        return (message_id if status=='succeeded' else None),status


def _restore_markup(buttons: object, bot):
    if not buttons:
        return None
    return InlineKeyboardMarkup.de_json({"inline_keyboard": buttons}, bot)


def _error_code(error: TelegramError) -> str:
    return "telegram_forbidden" if isinstance(error, Forbidden) else "telegram_bad_request"
