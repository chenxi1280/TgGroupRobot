from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.platform.scheduler.tasks.rename_monitor_task import _check_member_profile


class _Bot:
    def __init__(self, current_member) -> None:
        self.current_member = current_member
        self.sent: list[tuple[int, str]] = []
        self.get_member_calls: list[tuple[int, int]] = []

    async def get_chat_member(self, *, chat_id: int, user_id: int):
        self.get_member_calls.append((chat_id, user_id))
        return self.current_member

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))
        return SimpleNamespace(delete=lambda: None)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        chat_id=-100123,
        name_change_monitor_enabled=True,
        name_change_monitor_template_text=(
            "检测到用户{userId}修改{changeType}\n"
            "原{changeType}: {oldContent}\n"
            "新{changeType}: {newContent}"
        ),
        name_change_monitor_delete_after_seconds=0,
    )


@pytest.mark.asyncio
async def test_check_member_profile_sends_notice_and_updates_stored_user():
    current_user = SimpleNamespace(
        id=42,
        username="newalice",
        first_name="New",
        last_name="Alice",
        language_code="zh-CN",
    )
    bot = _Bot(SimpleNamespace(status="member", user=current_user))
    app = SimpleNamespace(bot=bot)
    member = SimpleNamespace(joined_at=dt.datetime.now(dt.UTC), updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    stored_user = SimpleNamespace(
        id=42,
        username="oldalice",
        first_name="Old",
        last_name="Alice",
        language_code="zh-CN",
        updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )

    changed = await _check_member_profile(app, object(), _settings(), member=member, stored_user=stored_user)

    assert changed is True
    assert bot.get_member_calls == [(-100123, 42)]
    assert [text for _, text in bot.sent] == [
        "检测到用户42修改用户名\n原用户名: oldalice\n新用户名: newalice",
        "检测到用户42修改昵称\n原昵称: Old Alice\n新昵称: New Alice",
    ]
    assert stored_user.username == "newalice"
    assert stored_user.first_name == "New"
    assert stored_user.last_name == "Alice"
    assert stored_user.updated_at > dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert member.updated_at > dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_check_member_profile_marks_left_member_inactive_without_notice():
    current_user = SimpleNamespace(
        id=42,
        username="newalice",
        first_name="New",
        last_name="Alice",
        language_code="zh-CN",
    )
    bot = _Bot(SimpleNamespace(status="left", user=current_user))
    app = SimpleNamespace(bot=bot)
    member = SimpleNamespace(joined_at=dt.datetime.now(dt.UTC), updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    stored_user = SimpleNamespace(
        id=42,
        username="oldalice",
        first_name="Old",
        last_name="Alice",
        language_code="zh-CN",
        updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )

    changed = await _check_member_profile(app, object(), _settings(), member=member, stored_user=stored_user)

    assert changed is False
    assert bot.sent == []
    assert member.joined_at is None
    assert stored_user.username == "oldalice"
