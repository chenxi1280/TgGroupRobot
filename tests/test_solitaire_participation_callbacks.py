from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import solitaire_participation_callbacks as callbacks
from backend.platform.db.schema.models.enums import SolitaireStatus


class _Session:
    async def commit(self):
        return None

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _SessionContext:
    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Db:
    def session_factory(self):
        return _SessionContext()


@pytest.mark.asyncio
async def test_join_solitaire_callback_logs_refresh_failure(monkeypatch):
    warnings: list[dict] = []
    sent_messages: list[str] = []

    async def fake_get_solitaire(session, solitaire_id: int):
        return SimpleNamespace(
            id=solitaire_id,
            chat_id=-10001,
            status=SolitaireStatus.active.value,
            max_participants=0,
            entries_rel=[],
            points_required=0,
            message_id=8899,
        )

    async def fake_join_solitaire(session, solitaire_id: int, user_id: int, username: str, content: str):
        return SimpleNamespace(success=True)

    async def fake_edit_message_text(**kwargs):
        raise RuntimeError("edit failed")

    async def fake_send_message(*, chat_id: int, text: str, **kwargs):
        sent_messages.append(text)
        return None

    async def fake_format_session_execute(stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(
            id=7,
            chat_id=-10001,
            status=SolitaireStatus.active.value,
            entries_rel=[],
            message_id=8899,
        ))

    def fake_warning(event: str, **fields):
        warnings.append({"event": event, **fields})

    monkeypatch.setattr(callbacks, "get_solitaire", fake_get_solitaire)
    monkeypatch.setattr(callbacks, "join_solitaire", fake_join_solitaire)
    monkeypatch.setattr(callbacks, "format_solitaire_message", lambda solitaire: "接龙文本")
    monkeypatch.setattr(callbacks, "get_join_solitaire_keyboard", lambda solitaire_id: None)
    monkeypatch.setattr(callbacks.log, "warning", fake_warning)

    class _FreshSession(_Session):
        async def execute(self, stmt):
            return await fake_format_session_execute(stmt)

    class _FreshSessionContext:
        def __init__(self, index: int):
            self.index = index

        async def __aenter__(self):
            return _FreshSession() if self.index == 2 else _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _CountingDb:
        def __init__(self):
            self.calls = 0

        def session_factory(self):
            self.calls += 1
            return _FreshSessionContext(self.calls)

    answers: list[str] = []

    async def fake_answer(text: str | None = None, *args, **kwargs):
        answers.append(text or "")

    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="join_solitaire:7", answer=fake_answer, message=SimpleNamespace(message_id=321)),
        effective_chat=SimpleNamespace(id=-10001),
        effective_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _CountingDb()}),
        bot=SimpleNamespace(edit_message_text=fake_edit_message_text, send_message=fake_send_message),
    )

    await callbacks.join_solitaire_callback(update, context)

    assert "参与成功！" in answers
    assert sent_messages and "已参与接龙" in sent_messages[0]
    assert warnings == [
        {
            "event": "solitaire_join_message_refresh_failed",
            "chat_id": -10001,
            "solitaire_id": 7,
            "message_id": 8899,
            "user_id": 42,
            "error": "edit failed",
        }
    ]
