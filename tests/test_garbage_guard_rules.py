from __future__ import annotations

from types import SimpleNamespace

from backend.features.moderation.services.garbage_guard_rules import (
    get_rule_config,
    is_global_whitelisted,
    set_global_whitelist_user_ids,
    set_rule_config,
)
from backend.features.moderation.services.garbage_guard_service import detect_garbage_violation


def _settings():
    return SimpleNamespace(
        anti_spam_rules={},
        anti_flood_enabled=False,
        anti_flood_messages=5,
        anti_flood_seconds=5,
        anti_flood_mute_duration=3600,
        anti_flood_cleanup_messages=False,
    )


def _message(text: str = "hello", **kwargs):
    user = kwargs.pop(
        "from_user",
        SimpleNamespace(id=123, username="alice", first_name="小明", last_name=None),
    )
    return SimpleNamespace(
        message_id=42,
        text=text,
        caption=None,
        from_user=user,
        reply_markup=kwargs.pop("reply_markup", None),
        forward_origin=kwargs.pop("forward_origin", None),
        forward_from_chat=kwargs.pop("forward_from_chat", None),
        forward_from=kwargs.pop("forward_from", None),
        forward_date=kwargs.pop("forward_date", None),
        sender_chat=None,
    )


def test_rule_config_updates_preserve_global_whitelist() -> None:
    settings = _settings()

    set_global_whitelist_user_ids(settings, [2, 1, 2])
    set_rule_config(settings, "block_links", {"enabled": True})

    assert is_global_whitelisted(settings, 1) is True
    assert is_global_whitelisted(settings, 3) is False
    assert get_rule_config(settings, "block_links")["enabled"] is True
    assert settings.anti_spam_rules["exception_user_ids"] == [1, 2]


def test_detects_link_button_forward_and_spam_user_rules() -> None:
    settings = _settings()

    set_rule_config(settings, "block_links", {"enabled": True})
    violation = detect_garbage_violation(settings, _message("visit https://example.com"))
    assert violation is not None
    assert violation.rule_id == "block_links"

    set_rule_config(settings, "block_links", {"enabled": False})
    set_rule_config(settings, "block_buttons", {"enabled": True})
    violation = detect_garbage_violation(settings, _message(reply_markup=SimpleNamespace(inline_keyboard=[[object()]])))
    assert violation is not None
    assert violation.rule_id == "block_buttons"

    set_rule_config(settings, "block_buttons", {"enabled": False})
    set_rule_config(settings, "block_forwards", {"enabled": True})
    violation = detect_garbage_violation(settings, _message(forward_origin=SimpleNamespace()))
    assert violation is not None
    assert violation.rule_id == "block_forwards"

    set_rule_config(settings, "block_forwards", {"enabled": False})
    set_rule_config(settings, "spam_user", {"enabled": True, "check_no_username": True, "check_foreign_name": True})
    violation = detect_garbage_violation(
        settings,
        _message(from_user=SimpleNamespace(id=123, username=None, first_name="Alice", last_name=None)),
    )
    assert violation is not None
    assert violation.rule_id == "spam_user"


def test_long_message_and_long_name_are_independent_rules() -> None:
    settings = _settings()
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 20})
    set_rule_config(settings, "long_name", {"enabled": False, "name_max_length": 2})

    violation = detect_garbage_violation(settings, _message("1" * 21))
    assert violation is not None
    assert violation.rule_id == "long_message"

    set_rule_config(settings, "long_message", {"enabled": False})
    violation = detect_garbage_violation(
        settings,
        _message("hi", from_user=SimpleNamespace(id=123, username="alice", first_name="很长很长的昵称", last_name=None)),
    )
    assert violation is None

    set_rule_config(settings, "long_name", {"enabled": True})
    violation = detect_garbage_violation(
        settings,
        _message("hi", from_user=SimpleNamespace(id=123, username="alice", first_name="很长很长的昵称", last_name=None)),
    )
    assert violation is not None
    assert violation.rule_id == "long_name"
