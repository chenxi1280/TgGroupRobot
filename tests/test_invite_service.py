from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.invite.services import invite_service


@pytest.mark.asyncio
async def test_revoke_invite_link_rejects_cross_chat(monkeypatch):
    async def fake_get_invite_link_in_chat(session, chat_id: int, link_id: int):
        assert chat_id == -1001
        assert link_id == 12
        return None

    monkeypatch.setattr(invite_service, "get_invite_link_in_chat", fake_get_invite_link_in_chat)

    result = await invite_service.revoke_invite_link(
        None,
        SimpleNamespace(),
        12,
        chat_id=-1001,
    )

    assert result.success is False
    assert result.reason == "not_found"


@pytest.mark.asyncio
async def test_delete_invite_link_rejects_cross_chat(monkeypatch):
    async def fake_get_invite_link_in_chat(session, chat_id: int, link_id: int):
        assert chat_id == -1001
        assert link_id == 12
        return None

    monkeypatch.setattr(invite_service, "get_invite_link_in_chat", fake_get_invite_link_in_chat)

    result = await invite_service.delete_invite_link(None, 12, chat_id=-1001)

    assert result is False


@pytest.mark.asyncio
async def test_update_invite_link_info_rejects_cross_chat(monkeypatch):
    async def fake_get_invite_link_in_chat(session, chat_id: int, link_id: int):
        assert chat_id == -1001
        assert link_id == 12
        return None

    monkeypatch.setattr(invite_service, "get_invite_link_in_chat", fake_get_invite_link_in_chat)

    result = await invite_service.update_invite_link_info(
        None,
        SimpleNamespace(),
        12,
        chat_id=-1001,
    )

    assert result is False
