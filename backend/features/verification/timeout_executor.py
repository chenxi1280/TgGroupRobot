from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

from telegram import ChatPermissions
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from backend.platform.delivery import DeliveryOutcome


ACTION_MUTE = "mute"
ACTION_KICK = "kick"
ACTION_UNRESTRICT = "unrestrict"
ACTION_NONE = "none"


@dataclass(frozen=True, slots=True)
class VerificationTimeoutPlan:
    challenge_id: int
    attempt_id: int
    chat_id: int
    user_id: int
    action: str
    duration_seconds: int


class VerificationTimeoutExecutor(Protocol):
    async def execute(self, plan: VerificationTimeoutPlan) -> DeliveryOutcome: ...


def _unrestricted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=False,
    )


class TelegramVerificationTimeoutExecutor:
    def __init__(self, bot) -> None:
        self._bot = bot

    async def execute(self, plan: VerificationTimeoutPlan) -> DeliveryOutcome:
        try:
            await self._execute_action(plan)
        except RetryAfter as exc:
            return DeliveryOutcome.retryable_failure("telegram_retry_after", str(exc))
        except (Forbidden, BadRequest) as exc:
            return DeliveryOutcome.permanent_failure(_error_code(exc), str(exc))
        except NetworkError as exc:
            return DeliveryOutcome.uncertain("telegram_network_unknown", str(exc))
        except ValueError as exc:
            return DeliveryOutcome.permanent_failure("invalid_timeout_action", str(exc))
        except TelegramError as exc:
            return DeliveryOutcome.uncertain("telegram_result_unknown", str(exc))
        return DeliveryOutcome.success(metadata={"action": plan.action})

    async def _execute_action(self, plan: VerificationTimeoutPlan) -> None:
        if plan.action == ACTION_NONE:
            return
        if plan.action == ACTION_KICK:
            await self._bot.ban_chat_member(chat_id=plan.chat_id, user_id=plan.user_id)
            return
        permissions = self._permissions_for(plan.action)
        kwargs = {
            "chat_id": plan.chat_id,
            "user_id": plan.user_id,
            "permissions": permissions,
        }
        if plan.action == ACTION_MUTE:
            kwargs["until_date"] = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=plan.duration_seconds)
        await self._bot.restrict_chat_member(**kwargs)

    @staticmethod
    def _permissions_for(action: str) -> ChatPermissions:
        if action == ACTION_MUTE:
            return ChatPermissions(can_send_messages=False)
        if action == ACTION_UNRESTRICT:
            return _unrestricted_permissions()
        raise ValueError(f"unsupported verification timeout action: {action}")


def _error_code(error: TelegramError) -> str:
    if isinstance(error, Forbidden):
        return "telegram_forbidden"
    return "telegram_bad_request"
