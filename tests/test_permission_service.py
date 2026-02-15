from __future__ import annotations

from types import SimpleNamespace

from bot.services.core.permission_service import get_bot_admin_ids, is_bot_admin_user


def _ctx(bot_admin_ids: str):
    settings = SimpleNamespace(bot_admin_ids=bot_admin_ids)
    application = SimpleNamespace(bot_data={"settings": settings})
    return SimpleNamespace(application=application)


def test_get_bot_admin_ids_parses_and_filters_invalid_values():
    ctx = _ctx(" 123, abc,456 , ,789 ")

    result = get_bot_admin_ids(ctx)

    assert result == {123, 456, 789}


def test_is_bot_admin_user_works_with_context_settings():
    ctx = _ctx("1001,1002")

    assert is_bot_admin_user(1001, ctx) is True
    assert is_bot_admin_user(9999, ctx) is False
