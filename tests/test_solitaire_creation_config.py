from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import solitaire_creation_config
from backend.features.activity.solitaire_shared import WAIT_CONFIG


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_publish_created_solitaire_rolls_back_when_group_send_fails(monkeypatch):
    replies: list[str] = []

    async def fake_reply_text(text: str, reply_markup=None):
        replies.append(text)

    async def fail_send_message(**kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(solitaire_creation_config, "format_solitaire_message", lambda entity: "formatted")
    monkeypatch.setattr(solitaire_creation_config, "get_join_solitaire_keyboard", lambda solitaire_id: "keyboard")

    update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=fake_reply_text))
    context = SimpleNamespace(bot=SimpleNamespace(send_message=fail_send_message))
    session = _Session()
    result = SimpleNamespace(entity=SimpleNamespace(id=7, message_id=None))

    published = await solitaire_creation_config._publish_created_solitaire(
        update,
        context,
        session,
        result=result,
        target_chat_id=-1001,
        state_chat_id=99,
        user_id=42,
    )

    assert published is False
    assert session.rollbacks == 1
    assert session.commits == 0
    assert replies == []


@pytest.mark.asyncio
async def test_solitaire_create_config_message_returns_wait_config_when_publish_fails(monkeypatch):
    replies: list[str] = []

    async def fake_reply_text(text: str, reply_markup=None):
        replies.append(text)

    class _SessionContext:
        def __init__(self, session) -> None:
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def __init__(self) -> None:
            self.sessions = [object(), object()]

        def session_factory(self):
            return _SessionContext(self.sessions.pop(0))

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(state_data={"target_chat_id": -1001})

    async def fake_create_solitaire(session, **kwargs):
        return SimpleNamespace(success=True, entity=SimpleNamespace(id=9))

    async def fake_publish(*args, **kwargs):
        return False

    monkeypatch.setattr(solitaire_creation_config, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(solitaire_creation_config, "create_solitaire", fake_create_solitaire)
    monkeypatch.setattr(solitaire_creation_config, "_publish_created_solitaire", fake_publish)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=99),
        effective_message=SimpleNamespace(
            text="测试接龙\n最大人数: 3",
            reply_text=fake_reply_text,
        ),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    result = await solitaire_creation_config.solitaire_create_config_message(update, context)

    assert result == WAIT_CONFIG
    assert replies == ["❌ 接龙创建失败，请检查机器人在目标群的发言权限后重试。"]
