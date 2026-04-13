from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.platform.db.schema.models.enums import VerificationMode
from backend.features.verification import verification_service


@pytest.mark.asyncio
async def test_solve_by_token_non_admin_expired_not_solved(monkeypatch):
    challenge = SimpleNamespace(
        solved=False,
        expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
        verification_type=VerificationMode.button.value,
    )
    updates: list[dict] = []

    async def fake_get(*args, **kwargs):
        return challenge

    async def fake_update(*args, **kwargs):
        updates.append(args[2])
        challenge.solved = args[2].get("solved", challenge.solved)
        return challenge

    monkeypatch.setattr(verification_service.ServiceBase, "_get_by_filters", fake_get)
    monkeypatch.setattr(verification_service.ServiceBase, "_update_entity", fake_update)

    result = await verification_service.solve_by_token(None, "token")

    assert result is challenge
    assert challenge.solved is False
    assert updates == []


@pytest.mark.asyncio
async def test_solve_by_token_admin_expired_can_be_solved(monkeypatch):
    challenge = SimpleNamespace(
        solved=False,
        expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
        verification_type=VerificationMode.admin.value,
    )
    updates: list[dict] = []

    async def fake_get(*args, **kwargs):
        return challenge

    async def fake_update(*args, **kwargs):
        updates.append(args[2])
        challenge.solved = args[2].get("solved", challenge.solved)
        return challenge

    monkeypatch.setattr(verification_service.ServiceBase, "_get_by_filters", fake_get)
    monkeypatch.setattr(verification_service.ServiceBase, "_update_entity", fake_update)

    result = await verification_service.solve_by_token(None, "token")

    assert result is challenge
    assert challenge.solved is True
    assert updates == [{"solved": True}]


@pytest.mark.asyncio
async def test_solve_by_token_scoped_rejects_wrong_user_or_chat(monkeypatch):
    challenge = SimpleNamespace(
        solved=False,
        chat_id=-1001,
        user_id=123,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=60),
        verification_type=VerificationMode.button.value,
    )

    async def fake_get(*args, **kwargs):
        return challenge

    async def fake_update(*args, **kwargs):
        raise AssertionError("should not update for mismatched scope")

    monkeypatch.setattr(verification_service.ServiceBase, "_get_by_filters", fake_get)
    monkeypatch.setattr(verification_service.ServiceBase, "_update_entity", fake_update)

    wrong_chat = await verification_service.solve_by_token_scoped(
        None,
        "token",
        expected_chat_id=-1002,
        expected_user_id=123,
    )
    wrong_user = await verification_service.solve_by_token_scoped(
        None,
        "token",
        expected_chat_id=-1001,
        expected_user_id=124,
    )

    assert wrong_chat is None
    assert wrong_user is None


@pytest.mark.asyncio
async def test_solve_by_token_scoped_solves_when_scope_matches(monkeypatch):
    challenge = SimpleNamespace(
        solved=False,
        chat_id=-1001,
        user_id=123,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=60),
        verification_type=VerificationMode.button.value,
    )
    updates: list[dict] = []

    async def fake_get(*args, **kwargs):
        return challenge

    async def fake_update(*args, **kwargs):
        updates.append(args[2])
        challenge.solved = args[2].get("solved", challenge.solved)
        return challenge

    monkeypatch.setattr(verification_service.ServiceBase, "_get_by_filters", fake_get)
    monkeypatch.setattr(verification_service.ServiceBase, "_update_entity", fake_update)

    result = await verification_service.solve_by_token_scoped(
        None,
        "token",
        expected_chat_id=-1001,
        expected_user_id=123,
    )

    assert result is challenge
    assert challenge.solved is True
    assert updates == [{"solved": True}]
