from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram import ChatMemberAdministrator, User

from backend.features.group_ops.services.chat_group_service import (
    format_group_guide_message,
    format_private_chat_current_title,
    get_user_managed_chats,
)


class _FakeResult:
    def __init__(self, chats):
        self._chats = chats

    def scalars(self):
        return self

    def all(self):
        return list(self._chats)


class _FakeSession:
    def __init__(self, chats):
        self._chats = chats

    async def execute(self, stmt):
        return _FakeResult(self._chats)


class _FakeSessionContext:
    def __init__(self, chats):
        self._chats = chats

    async def __aenter__(self):
        return _FakeSession(self._chats)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, chats):
        self._chats = chats

    def session_factory(self):
        return _FakeSessionContext(self._chats)


@pytest.mark.asyncio
async def test_get_user_managed_chats_uses_db_title_without_extra_get_chat():
    chats = [
        SimpleNamespace(id=-1001, title="测试群A", type="supergroup"),
        SimpleNamespace(id=-1002, title="测试群B", type="group"),
    ]
    db = _FakeDb(chats)

    member_calls: list[tuple[int, int]] = []

    class _FakeBot:
        async def get_chat_member(self, chat_id: int, user_id: int):
            member_calls.append((chat_id, user_id))
            return ChatMemberAdministrator(
                user=User(id=user_id, first_name="Admin", is_bot=False),
                can_be_edited=False,
                is_anonymous=False,
                can_manage_chat=True,
                can_delete_messages=True,
                can_manage_video_chats=True,
                can_restrict_members=True,
                can_promote_members=True,
                can_change_info=True,
                can_invite_users=True,
                can_post_stories=True,
                can_edit_stories=True,
                can_delete_stories=True,
            )

        async def get_chat(self, chat_id: int):
            raise AssertionError("get_chat should not be called when db title is available")

    result = await get_user_managed_chats(db, user_id=42, bot=_FakeBot())

    assert member_calls == [(-1001, 42), (-1002, 42)]
    assert result == [(-1001, "测试群A", True), (-1002, "测试群B", True)]


def test_private_current_chat_hint_points_to_health_check_and_test_loop():
    text = format_private_chat_current_title("测试群")

    assert "当前管理: 测试群" in text
    assert "健康检查" in text
    assert "先预览" in text
    assert "群内测试一次" in text


def test_group_guide_message_describes_admin_setup_flow():
    text = format_group_guide_message("demo_bot")

    assert "前往设置" in text
    assert "健康检查" in text
    assert "预览" in text
    assert "测试账号触发一次" in text
