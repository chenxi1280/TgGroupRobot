from __future__ import annotations

from types import SimpleNamespace

from backend.shared.services.command_config_service import (
    get_command_alias,
    get_command_config,
    is_command_enabled,
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

    set_command_alias(settings, "start", "清空")
    assert get_command_alias(settings, "start") is None


def test_command_config_normalizes_missing_payload() -> None:
    settings = SimpleNamespace(command_config_enabled=True, command_config=None)
    config = get_command_config(settings)
    assert "commands" in config
    assert config["commands"]["start"]["enabled"] is True
