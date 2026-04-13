from __future__ import annotations

from backend.features.automation.services.scheduled_message_service_mutations import (
    ScheduledMessageMutationMixin,
)
from backend.features.automation.services.scheduled_message_service_queries import (
    ScheduledMessageQueryMixin,
)
from backend.features.automation.services.scheduled_message_service_validation import (
    ScheduledMessageValidationMixin,
)
from backend.shared.services.base import ServiceBase


class ScheduledMessageService(
    ScheduledMessageMutationMixin,
    ScheduledMessageQueryMixin,
    ScheduledMessageValidationMixin,
    ServiceBase,
):
    """定时消息任务服务。"""
