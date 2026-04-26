from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.guess_service_parsing import parse_deadline, parse_options, parse_ratio
from backend.features.activity.services.guess_service_queries import (
    close_due_events,
    close_due_event,
    count_events_by_status,
    get_event,
    list_due_event_ids,
    get_or_create_setting,
    get_running_event_by_keyword,
    list_events,
    update_setting,
)
from backend.features.activity.services.guess_service_runtime import (
    cancel_event,
    create_event,
    format_event_preview,
    format_event_runtime,
    place_bet,
    resolve_user_id,
    settle_event,
)
