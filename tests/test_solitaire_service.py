from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity.services import solitaire_service


@pytest.mark.asyncio
async def test_close_solitaire_rejects_cross_chat(monkeypatch):
    async def fake_get_solitaire_in_chat(session, chat_id: int, solitaire_id: int):
        assert chat_id == -1001
        assert solitaire_id == 12
        return None

    monkeypatch.setattr(solitaire_service, "get_solitaire_in_chat", fake_get_solitaire_in_chat)

    result = await solitaire_service.close_solitaire(None, 12, chat_id=-1001)

    assert result.success is False
    assert result.reason == "not_found"


@pytest.mark.asyncio
async def test_delete_solitaire_rejects_cross_chat(monkeypatch):
    async def fake_get_solitaire_in_chat(session, chat_id: int, solitaire_id: int):
        assert chat_id == -1001
        assert solitaire_id == 12
        return None

    monkeypatch.setattr(solitaire_service, "get_solitaire_in_chat", fake_get_solitaire_in_chat)

    result = await solitaire_service.delete_solitaire(None, 12, chat_id=-1001)

    assert result is False


@pytest.mark.asyncio
async def test_get_solitaire_in_chat_accepts_matching_chat(monkeypatch):
    solitaire = SimpleNamespace(id=12, chat_id=-1001)

    class _Result:
        def scalar_one_or_none(self):
            return solitaire

    class _Session:
        async def execute(self, stmt):
            return _Result()

    result = await solitaire_service.get_solitaire_in_chat(_Session(), -1001, 12)

    assert result is solitaire


@pytest.mark.asyncio
async def test_create_solitaire_returns_generic_error_when_flush_fails():
    class _Session:
        def add(self, obj) -> None:
            return None

        async def flush(self) -> None:
            raise RuntimeError("db down")

    result = await solitaire_service.create_solitaire(
        _Session(),
        chat_id=-1001,
        created_by_user_id=42,
        title="测试接龙",
    )

    assert result.success is False
    assert result.reason == "error"
    assert result.error == "接龙创建失败，请稍后重试"
