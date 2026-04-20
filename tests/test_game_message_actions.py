from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import game_message_actions, game_runtime_actions


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        return None


class _Db:
    def __init__(self) -> None:
        self.session_factory = lambda: _Session()


class _CallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.id = f"cb-{data}"
        self.answers: list[dict] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answers.append({"text": text, "show_alert": show_alert})


def _group_update(text: str):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(
            id=42,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh",
        ),
        effective_message=SimpleNamespace(text=text, message_id=99),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected_text"),
    [
        ("快三规则", "🎮 快三已开启"),
        ("快3规则", "🎮 快三已开启"),
        ("快三统计", "🎲 快三统计"),
        ("快3统计", "🎲 快三统计"),
        ("黑杰克规则", "🎮 黑杰克已开启"),
        ("黑杰克统计", "🃏 黑杰克统计"),
    ],
)
async def test_game_tip_commands_are_handled_and_reply(monkeypatch, command: str, expected_text: str):
    replies: list[tuple[int, str, int]] = []

    async def fake_get_or_create_setting(session, chat_id: int):
        return SimpleNamespace(
            k3_enabled=True,
            blackjack_enabled=True,
            rake_ratio="0.1",
            delete_game_message_mode="keep",
        )

    async def fake_build_user_game_stats(session, chat_id: int, user_id: int, game_type: str, title: str):
        return f"{title}统计\n总局数：0"

    async def fake_reply(context, *, chat_id: int, text: str, reply_to_message_id: int, **kwargs):
        replies.append((chat_id, text, reply_to_message_id))
        return SimpleNamespace(ok=True, message_id=100)

    monkeypatch.setattr(game_message_actions, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(game_message_actions, "build_user_game_stats", fake_build_user_game_stats)
    monkeypatch.setattr(game_message_actions.PublishService, "reply", fake_reply)

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    handled = await game_message_actions.handle_game_message(_group_update(command), context)

    assert handled is True
    assert replies
    assert replies[0][0] == -1001
    assert replies[0][2] == 99
    assert expected_text in replies[0][1]
    assert "抽水比例" not in replies[0][1]


@pytest.mark.asyncio
async def test_game_runtime_refresh_callback_returns_visible_feedback(monkeypatch):
    shown: list[int] = []

    async def fake_show_k3_panel(context, db, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(game_runtime_actions, "show_k3_panel", fake_show_k3_panel)

    query = _CallbackQuery("gmrun:k3:refresh:-1001")
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await game_runtime_actions.handle_game_runtime_callback(update, context)

    assert shown == [-1001]
    assert query.answers == [{"text": "已刷新快三面板", "show_alert": False}]
