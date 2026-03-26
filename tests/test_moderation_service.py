from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.services.moderation.moderation_service as moderation_service
from bot.services.moderation.moderation_service import (
    ModerationActionResolution,
    build_moderation_action_label,
    build_moderation_notice,
    normalize_moderation_actor_id,
    record_violation,
    resolve_effective_action,
    should_exempt_admin,
)


@pytest.mark.asyncio
async def test_should_exempt_admin_accepts_group_admin_and_bot_admin(monkeypatch):
    async def fake_is_user_admin(context, chat_id, user_id):
        return user_id == 10

    monkeypatch.setattr(moderation_service, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(moderation_service, "is_bot_admin_user", lambda user_id, context=None: user_id == 20)

    context = SimpleNamespace(bot=SimpleNamespace())

    assert await should_exempt_admin(context, -100, 10, True) is True
    assert await should_exempt_admin(context, -100, 20, True) is True
    assert await should_exempt_admin(context, -100, 30, True) is False
    assert await should_exempt_admin(context, -100, 10, False) is False


@pytest.mark.asyncio
async def test_resolve_effective_action_downgrades_for_channel_and_admin(monkeypatch):
    async def fake_get_chat_member(chat_id, user_id):
        return SimpleNamespace(status="creator")

    context = SimpleNamespace(
        bot=SimpleNamespace(
            get_chat_member=fake_get_chat_member
        )
    )

    admin_resolution = await resolve_effective_action(context, -100, 123, "mute")
    assert admin_resolution.action == "delete"
    assert "群主/管理员" in admin_resolution.fallback_reason

    channel_resolution = await resolve_effective_action(context, -100, 123, "ban", sender_chat_id=-200)
    assert channel_resolution.action == "delete"
    assert "频道身份" in channel_resolution.fallback_reason


def test_notice_and_action_label_helpers():
    assert normalize_moderation_actor_id(123, None) == 123
    assert normalize_moderation_actor_id(None, 456) == -456
    assert build_moderation_action_label("mute", 600) == "禁言 600 秒"
    assert build_moderation_action_label("delete") == "删除消息"

    notice = build_moderation_notice(
        "🚫 测试",
        "用户A",
        "rule_x",
        "删除消息",
        fallback_reason="已降级",
        extra_lines=["额外信息"],
    )
    assert "🚫 测试" in notice
    assert "用户: 用户A" in notice
    assert "规则: rule_x" in notice
    assert "处罚: 删除消息" in notice
    assert "说明: 已降级" in notice
    assert "额外信息" in notice


@pytest.mark.asyncio
async def test_record_violation_creates_audit_row():
    class FakeSession:
        def __init__(self):
            self.items = []

        def add(self, item):
            self.items.append(item)

        async def flush(self):
            return None

    session = FakeSession()
    await record_violation(
        session,
        chat_id=-100,
        user_id=123,
        message_id=456,
        rule="anti_flood",
        detail="count=5",
        action="delete",
    )

    assert len(session.items) == 1
    row = session.items[0]
    assert row.chat_id == -100
    assert row.user_id == 123
    assert row.message_id == 456
    assert row.rule == "anti_flood"
    assert row.detail == "count=5"
    assert row.action == "delete"
