from __future__ import annotations

from types import SimpleNamespace

from backend.features.group_ops.start_handler import (
    _private_start_text,
    _targets_from_private_state,
)
from backend.features.group_ops.start_payloads import extract_start_payload
from backend.platform.db.schema.models.enums import ConversationStateType


def test_extract_start_payload_handles_command_and_missing_payload() -> None:
    assert extract_start_payload("/start tloc_-1001") == "tloc_-1001"
    assert extract_start_payload("/start") == ""
    assert extract_start_payload(None) == ""


def test_private_start_text_prefers_current_chat_title() -> None:
    chats = [(-1001, "一群", True), (-1002, "二群", False)]

    text = _private_start_text(
        chats,
        current_chat_id=-1002,
        bot_username="robot",
        has_teacher_rows=True,
    )

    assert "二群" in text
    assert "老师" in text


def test_cancel_targets_restore_previous_selected_chat_only_for_member_location() -> None:
    state = SimpleNamespace(
        state_type=ConversationStateType.teacher_search_member_location_input.value,
        state_data={"previous_selected_chat_id": -2002, "target_chat_id": -1001},
    )

    targets = _targets_from_private_state(state, -1001)

    assert targets.target_chat_id == -2002
    assert targets.teacher_self_chat_id is None


def test_cancel_targets_return_teacher_profile_destination() -> None:
    state = SimpleNamespace(
        state_type=ConversationStateType.teacher_self_price_input.value,
        state_data={"target_chat_id": -1001},
    )

    targets = _targets_from_private_state(state, -2002)

    assert targets.target_chat_id == -2002
    assert targets.teacher_self_chat_id == -1001
