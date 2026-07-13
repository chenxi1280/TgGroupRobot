from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from backend.platform.delivery import DeliveryOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class GarageForwardPlan:
    delivery_id: int
    message_map_id: int
    chat_id: int
    source_channel_id: int
    source_message_id: int
    reply_markup_snapshot: dict[str, Any] | None


class GarageForwardExecutor(Protocol):
    async def execute(self, plan: GarageForwardPlan) -> DeliveryOutcome: ...


class TelegramGarageForwardExecutor:
    def __init__(self, bot) -> None:
        self._bot = bot

    async def execute(self, plan: GarageForwardPlan) -> DeliveryOutcome:
        try:
            copied = await self._bot.copy_message(
                chat_id=plan.chat_id,
                from_chat_id=plan.source_channel_id,
                message_id=plan.source_message_id,
                reply_markup=self._restore_markup(plan.reply_markup_snapshot),
            )
        except RetryAfter as exc:
            return DeliveryOutcome.retryable_failure("telegram_retry_after", str(exc))
        except (Forbidden, BadRequest) as exc:
            return DeliveryOutcome.permanent_failure(_telegram_error_code(exc), str(exc))
        except NetworkError as exc:
            return DeliveryOutcome.uncertain("telegram_network_unknown", str(exc))
        except TelegramError as exc:
            return DeliveryOutcome.uncertain("telegram_result_unknown", str(exc))
        return DeliveryOutcome.success(message_id=int(copied.message_id))

    def _restore_markup(self, snapshot: dict[str, Any] | None):
        if snapshot is None:
            return None
        return InlineKeyboardMarkup.de_json(snapshot, self._bot)


def _telegram_error_code(error: TelegramError) -> str:
    if isinstance(error, Forbidden):
        return "telegram_forbidden"
    return "telegram_bad_request"
