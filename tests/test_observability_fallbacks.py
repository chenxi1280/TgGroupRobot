from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from backend.features.activity.services import game_base
from backend.features.web_admin import auth_service
from backend.platform.state.conversation_state_service import _parse_expire_at
from backend.shared.config_parser import DateTimeParser


def test_parse_expire_at_logs_invalid_value(monkeypatch):
    warnings: list[dict] = []

    def fake_warning(event: str, **fields):
        warnings.append({"event": event, **fields})

    monkeypatch.setattr("backend.platform.state.conversation_state_service.log.warning", fake_warning)

    assert _parse_expire_at({"__expire_at__": "bad-iso"}) is None
    assert warnings == [{"event": "conversation_state_expire_at_parse_failed", "expire_at_raw": "bad-iso"}]


def test_datetime_parser_logs_failed_fallbacks(monkeypatch):
    warnings: list[dict] = []

    def fake_warning(event: str, **fields):
        warnings.append({"event": event, **fields})

    monkeypatch.setattr("backend.shared.config_parser.log.warning", fake_warning)

    assert DateTimeParser.parse_minutes("abc") is None
    assert DateTimeParser.parse_datetime("not-a-date") is None
    assert warnings == [
        {"event": "parse_minutes_failed", "raw_value": "abc"},
        {"event": "parse_datetime_failed", "raw_value": "not-a-date", "format": "%Y-%m-%d %H:%M"},
    ]


def test_game_base_logs_parse_fallbacks(monkeypatch):
    warnings: list[dict] = []

    def fake_warning(event: str, **fields):
        warnings.append({"event": event, **fields})

    monkeypatch.setattr(game_base.log, "warning", fake_warning)

    assert game_base.get_round_points_chat_id(SimpleNamespace(result_data={"points_chat_id": "oops"}), 77) == 77
    assert game_base.get_rake_ratio_value(SimpleNamespace(chat_id=-10001, rake_ratio="bad")) == Decimal("0")
    assert warnings == [
        {
            "event": "game_round_points_chat_id_parse_failed",
            "default_chat_id": 77,
            "raw_value": "oops",
        },
        {
            "event": "game_rake_ratio_parse_failed",
            "chat_id": -10001,
            "raw_value": "bad",
        },
    ]


def test_verify_password_logs_invalid_hash(monkeypatch):
    warnings: list[dict] = []

    def fake_warning(event: str, **fields):
        warnings.append({"event": event, **fields})

    monkeypatch.setattr(auth_service.log, "warning", fake_warning)

    assert auth_service.verify_password("secret", "broken-hash") is False
    assert warnings == [{"event": "admin_password_hash_parse_failed", "password_hash": "broken-hash"}]
