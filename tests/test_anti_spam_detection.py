from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.moderation.services.anti_spam_detection import detect_spam_violation


class _Tracker:
    def __init__(self, *, repeated: bool = False) -> None:
        self.repeated = repeated

    async def check_repeat(self, **kwargs):
        return self.repeated, [kwargs["message_id"]], "repeat detected"


def _settings(rules: dict[str, object]):
    return SimpleNamespace(
        anti_spam_rules=rules,
        anti_spam_repeat_messages=3,
        anti_spam_repeat_seconds=10,
    )


def _message(**updates):
    values = {
        "message_id": 9,
        "text": "normal",
        "caption": None,
        "sender_chat": None,
        "forward_from_chat": None,
        "forward_from": None,
        "forward_origin": None,
        "entities": [],
        "caption_entities": [],
        "photo": None,
        "video": None,
        "animation": None,
        "document": None,
        "from_user": SimpleNamespace(first_name="Alice", last_name=None),
    }
    values.update(updates)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_detection_preserves_rule_priority() -> None:
    violation = await detect_spam_violation(
        _settings({"banned_accounts": True, "banned_user_ids": [42], "block_links": True}),
        _message(text="https://example.com"),
        -1001,
        user_id=42,
        tracker=_Tracker(),
    )

    assert violation.blocked is True
    assert violation.rule == "banned_account"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rules", "message", "expected_rule"),
    [
        (
            {"block_forwards": True, "blocked_forward_chat_ids": [-2002]},
            _message(forward_from_chat=SimpleNamespace(id=-2002)),
            "forward_source",
        ),
        ({"block_links": True}, _message(text="visit https://example.com"), "link"),
        (
            {"ai_image_ads": True},
            _message(text="推广", photo=[SimpleNamespace(file_id="photo")]),
            "image_ads",
        ),
        (
            {"block_long_content": True, "message_max_length": 3},
            _message(text="long"),
            "long_message",
        ),
    ],
)
async def test_detection_classifies_independent_signals(rules, message, expected_rule) -> None:
    violation = await detect_spam_violation(
        _settings(rules),
        message,
        -1001,
        user_id=42,
        tracker=_Tracker(),
    )

    assert violation.blocked is True
    assert violation.rule == expected_rule


@pytest.mark.asyncio
async def test_detection_reports_repeat_message_ids() -> None:
    violation = await detect_spam_violation(
        _settings({"flood_attack": True}),
        _message(text="repeat"),
        -1001,
        user_id=42,
        tracker=_Tracker(repeated=True),
    )

    assert violation.rule == "repeat_flood"
    assert violation.message_ids_to_delete == [9]


@pytest.mark.asyncio
async def test_exception_user_bypasses_all_rules() -> None:
    violation = await detect_spam_violation(
        _settings(
            {
                "exception_user_ids": [42],
                "banned_accounts": True,
                "banned_user_ids": [42],
            }
        ),
        _message(),
        -1001,
        user_id=42,
        tracker=_Tracker(),
    )

    assert violation.blocked is False
