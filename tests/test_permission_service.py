from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.shared.services.permission_service import (
    PermissionPolicyService,
    get_bot_admin_ids,
    is_bot_admin_user,
)


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


@pytest.mark.asyncio
async def test_permission_policy_allows_bot_admin_without_group_check(monkeypatch):
    ctx = _ctx("1001")

    async def fake_is_user_admin(*args, **kwargs):
        raise AssertionError("group admin check should not be called for bot admin")

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    assert await PermissionPolicyService.can_manage(ctx, -1001, 1001) is True


@pytest.mark.asyncio
async def test_permission_policy_allows_group_admin_for_common_capability(monkeypatch):
    ctx = _ctx("")

    async def fake_is_user_admin(*args, **kwargs):
        return True

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    assert await PermissionPolicyService.can_manage(ctx, -1001, 2002, capability="settings") is True


@pytest.mark.asyncio
async def test_permission_policy_denies_non_admin_for_common_capability(monkeypatch):
    ctx = _ctx("")

    async def fake_is_user_admin(*args, **kwargs):
        return False

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    assert await PermissionPolicyService.can_manage(ctx, -1001, 2002, capability="settings") is False


@pytest.mark.asyncio
async def test_permission_policy_requires_bot_admin_for_system_capability(monkeypatch):
    ctx = _ctx("")

    async def fake_is_user_admin(*args, **kwargs):
        return True

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    assert await PermissionPolicyService.can_manage(ctx, -1001, 2002, capability="bot_admin") is False


@pytest.mark.asyncio
async def test_permission_policy_reports_unknown_capability_without_check(monkeypatch):
    ctx = _ctx("")

    async def fake_is_user_admin(*args, **kwargs):
        raise AssertionError("group admin check should not be called for unknown capability")

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    decision = await PermissionPolicyService.evaluate(ctx, -1001, 2002, capability="unknown_capability")

    assert decision.allowed is False
    assert decision.reason == "unknown_capability"


@pytest.mark.asyncio
async def test_permission_policy_requires_context_for_group_capability(monkeypatch):
    async def fake_is_user_admin(*args, **kwargs):
        raise AssertionError("group admin check should not be called without context")

    monkeypatch.setattr("backend.shared.services.permission_service.is_user_admin", fake_is_user_admin)

    decision = await PermissionPolicyService.evaluate(None, -1001, 2002, capability="settings")

    assert decision.allowed is False
    assert decision.reason == "context_required"


def test_get_bot_admin_ids_falls_back_to_global_settings(monkeypatch):
    from backend.shared.services import permission_service

    monkeypatch.setattr(permission_service, "get_settings", lambda: SimpleNamespace(bot_admin_ids="7001,7002"))
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={}))

    assert get_bot_admin_ids(ctx) == {7001, 7002}


@pytest.mark.asyncio
async def test_permission_policy_respects_owner_only(monkeypatch):
    ctx = _ctx("")

    async def fake_resolve_chat_policy(context, chat_id: int):
        return "owner_only"

    async def fake_get_chat_member(*, chat_id: int, user_id: int):
        return SimpleNamespace(status="administrator", can_promote_members=True)

    monkeypatch.setattr(PermissionPolicyService, "_resolve_chat_policy", fake_resolve_chat_policy)
    ctx.bot = SimpleNamespace(get_chat_member=fake_get_chat_member)

    decision = await PermissionPolicyService.evaluate(ctx, -1001, 2002, capability="settings")

    assert decision.allowed is False
    assert decision.reason == "group_admin_required"


@pytest.mark.asyncio
async def test_permission_policy_respects_can_change_info(monkeypatch):
    ctx = _ctx("")

    async def fake_resolve_chat_policy(context, chat_id: int):
        return "can_change_info"

    async def fake_get_chat_member(*, chat_id: int, user_id: int):
        return SimpleNamespace(status="administrator", can_change_info=True, can_promote_members=False)

    monkeypatch.setattr(PermissionPolicyService, "_resolve_chat_policy", fake_resolve_chat_policy)
    ctx.bot = SimpleNamespace(get_chat_member=fake_get_chat_member)

    decision = await PermissionPolicyService.evaluate(ctx, -1001, 2002, capability="settings")

    assert decision.allowed is True
    assert decision.reason == "group_admin"
