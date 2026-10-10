from __future__ import annotations

from types import SimpleNamespace

from backend.shared.services.command_config_service import (
    get_command_alias,
    get_command_config,
    is_command_enabled,
    list_command_definitions,
    set_command_alias,
    set_command_enabled,
)


def test_command_config_defaults_enable_all() -> None:
    settings = SimpleNamespace(command_config_enabled=False, command_config={})
    assert is_command_enabled(settings, "start") is True
    assert get_command_alias(settings, "start") is None


def test_command_config_toggle_and_alias() -> None:
    settings = SimpleNamespace(command_config_enabled=True, command_config={})

    set_command_enabled(settings, "start", False)
    assert is_command_enabled(settings, "start") is False

    set_command_alias(settings, "start", "/BEGIN")
    assert get_command_alias(settings, "start") == "begin"

    set_command_alias(settings, "start", None)
    assert get_command_alias(settings, "start") is None


def test_command_config_normalizes_missing_payload() -> None:
    settings = SimpleNamespace(command_config_enabled=True, command_config=None)
    config = get_command_config(settings)
    assert "commands" in config
    assert config["commands"]["start"]["enabled"] is True


def test_command_config_covers_fixed_text_entries_without_alias() -> None:
    keys = {item["key"]: item for item in list_command_definitions()}
    for key in {"teacher_search", "open_teachers", "car_review", "car_review_rank", "invite_rank", "lottery", "solitaire"}:
        assert key in keys
        assert keys[key]["allow_alias"] is False

    settings = SimpleNamespace(command_config_enabled=True, command_config={})
    set_command_enabled(settings, "teacher_search", False)
    set_command_alias(settings, "teacher_search", "search")

    assert is_command_enabled(settings, "teacher_search") is False
    assert get_command_alias(settings, "teacher_search") is None


def test_invalid_and_conflicting_aliases_preserve_existing_configuration():
    import pytest
    settings = SimpleNamespace(command_config_enabled=True, command_config={})
    set_command_alias(settings, "start", "begin")
    for invalid in ["中文", "a" * 33, "admin", "cancel"]:
        with pytest.raises(ValueError):
            set_command_alias(settings, "start", invalid)
        assert get_command_alias(settings, "start") == "begin"
    with pytest.raises(ValueError):
        set_command_alias(settings, "points", "begin")


def test_historical_alias_collisions_are_reported_and_not_dispatched():
    from backend.shared.services.command_config_service import command_alias_conflicts
    from backend.features.group_ops.command_alias_handler import _build_alias_map
    settings = SimpleNamespace(command_config_enabled=True, command_config={"commands": {
        "start": {"enabled": True, "alias": "same"},
        "points": {"enabled": True, "alias": "same"},
        "rank": {"enabled": True, "alias": "sign"}}})
    assert command_alias_conflicts(settings) == {"same", "sign"}
    assert _build_alias_map(settings) == {}
