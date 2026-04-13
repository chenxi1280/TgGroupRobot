from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.admin_handler import handle_garage_forward_input
from backend.features.garage.garage_forward_handler import garage_forward_channel_post_handler
from backend.features.garage.services.garage_forward_service import GarageForwardService
from backend.platform.state import state_service
from backend.shared.callback_parser import CallbackParser


class _Session:
    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def flush(self):
        return None


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_garage_forward_channel_post_copies_message_and_records(monkeypatch):
    copied_calls: list[tuple[int, int, int]] = []
    finalized: list[tuple[int, int]] = []
    audits: list[tuple[int, str, str]] = []

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="all", keyword_rules=[]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_claim_forward_slot(session, *, chat_id, source_channel_id, source_message_id):
        return SimpleNamespace(id=77)

    async def fake_finalize_forward(session, *, message_map_id, target_message_id):
        finalized.append((message_map_id, target_message_id))

    async def fake_abandon_forward_slot(session, *, message_map_id):
        return True

    async def fake_append_audit(session, *, chat_id, source_channel_id, action, result, reason=None, source_message_id=None):
        audits.append((chat_id, action, result))

    async def fake_copy_message(*, chat_id, from_chat_id, message_id, reply_markup=None):
        copied_calls.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=999)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(GarageForwardService, "claim_forward_slot", fake_claim_forward_slot)
    monkeypatch.setattr(GarageForwardService, "finalize_forward", fake_finalize_forward)
    monkeypatch.setattr(GarageForwardService, "abandon_forward_slot", fake_abandon_forward_slot)
    monkeypatch.setattr(GarageForwardService, "append_audit", fake_append_audit)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-10001, type="channel"),
        effective_message=SimpleNamespace(
            message_id=321,
            text="同步内容",
            caption=None,
            photo=None,
            video=None,
            document=None,
            animation=None,
            audio=None,
            voice=None,
            video_note=None,
            sticker=None,
        ),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}),
        bot=SimpleNamespace(copy_message=fake_copy_message),
    )

    await garage_forward_channel_post_handler(update, context)

    assert copied_calls == [(-20001, -10001, 321)]
    assert finalized == [(77, 999)]
    assert audits == [(-20001, "copy", "success")]


@pytest.mark.asyncio
async def test_garage_forward_keyword_mode_respects_keyword_rules(monkeypatch):
    copied_calls: list[tuple[int, int, int]] = []

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="keyword", keyword_rules=["榜单"]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_claim_forward_slot(session, *, chat_id, source_channel_id, source_message_id):
        return SimpleNamespace(id=88)

    async def fake_finalize_forward(*args, **kwargs):
        return None

    async def fake_abandon_forward_slot(*args, **kwargs):
        return None

    async def fake_append_audit(*args, **kwargs):
        return None

    async def fake_copy_message(*, chat_id, from_chat_id, message_id):
        copied_calls.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=1000)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(GarageForwardService, "claim_forward_slot", fake_claim_forward_slot)
    monkeypatch.setattr(GarageForwardService, "finalize_forward", fake_finalize_forward)
    monkeypatch.setattr(GarageForwardService, "abandon_forward_slot", fake_abandon_forward_slot)
    monkeypatch.setattr(GarageForwardService, "append_audit", fake_append_audit)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-10001, type="channel"),
        effective_message=SimpleNamespace(
            message_id=654,
            text="普通消息",
            caption=None,
            photo=None,
            video=None,
            document=None,
            animation=None,
            audio=None,
            voice=None,
            video_note=None,
            sticker=None,
        ),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}),
        bot=SimpleNamespace(copy_message=fake_copy_message),
    )

    await garage_forward_channel_post_handler(update, context)

    assert copied_calls == []


@pytest.mark.asyncio
async def test_garage_forward_duplicate_claim_skips_copy_and_records_audit(monkeypatch):
    copied_calls: list[tuple[int, int, int]] = []
    audits: list[tuple[int, str, str, str | None]] = []

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="all", keyword_rules=[]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_claim_forward_slot(session, *, chat_id, source_channel_id, source_message_id):
        return None

    async def fake_finalize_forward(*args, **kwargs):
        return None

    async def fake_abandon_forward_slot(*args, **kwargs):
        return None

    async def fake_append_audit(session, *, chat_id, source_channel_id, action, result, reason=None, source_message_id=None):
        audits.append((chat_id, action, result, reason))

    async def fake_copy_message(*, chat_id, from_chat_id, message_id):
        copied_calls.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=1000)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(GarageForwardService, "claim_forward_slot", fake_claim_forward_slot)
    monkeypatch.setattr(GarageForwardService, "finalize_forward", fake_finalize_forward)
    monkeypatch.setattr(GarageForwardService, "abandon_forward_slot", fake_abandon_forward_slot)
    monkeypatch.setattr(GarageForwardService, "append_audit", fake_append_audit)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-10001, type="channel"),
        effective_message=SimpleNamespace(
            message_id=777,
            text="重复同步内容",
            caption=None,
            photo=None,
            video=None,
            document=None,
            animation=None,
            audio=None,
            voice=None,
            video_note=None,
            sticker=None,
        ),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}),
        bot=SimpleNamespace(copy_message=fake_copy_message),
    )

    await garage_forward_channel_post_handler(update, context)

    assert copied_calls == []
    assert audits == [(-20001, "copy", "skipped", "duplicate_message")]


@pytest.mark.asyncio
async def test_handle_garage_forward_input_updates_keywords(monkeypatch):
    replies: list[str] = []
    updates: list[tuple[int, list[str]]] = []
    clear_calls: list[tuple[int, int]] = []
    shown: list[int] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_update_setting(session, chat_id, *, enabled=None, sync_mode=None, keyword_rules=None):
        updates.append((chat_id, keyword_rules or []))
        return None

    async def fake_clear_user_state(session, *, chat_id, user_id):
        clear_calls.append((chat_id, user_id))

    async def fake_show(update, context, chat_id):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(state_service, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_garage_forward_prompt", fake_show)
    monkeypatch.setattr(GarageForwardService, "update_setting", fake_update_setting)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(bot=SimpleNamespace(get_chat=None))
    session = _Session()
    state = SimpleNamespace(
        state_type="garage_forward_keyword_input",
        state_data={"target_chat_id": -10001},
        chat_id=42,
    )

    await handle_garage_forward_input(update, context, session, state, "榜单,开奖\n榜单")

    assert updates == [(-10001, ["榜单", "开奖"])]
    assert clear_calls == [(-10001, 42), (42, 42)]
    assert shown == [-10001]
    assert any("已更新关键词规则" in text for text in replies)


@pytest.mark.asyncio
async def test_handle_garage_forward_input_rejects_non_channel_source(monkeypatch):
    replies: list[str] = []
    added_sources: list[tuple[int, int, str | None]] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_add_source(session, *, chat_id, source_channel_id, source_name=None):
        added_sources.append((chat_id, source_channel_id, source_name))
        return None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(GarageForwardService, "add_source", fake_add_source)

    async def fake_get_chat(raw_value):
        return SimpleNamespace(id=-20001, type="supergroup", title="不是频道")

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(bot=SimpleNamespace(get_chat=fake_get_chat))
    session = _Session()
    state = SimpleNamespace(
        state_type="garage_forward_source_input",
        state_data={"target_chat_id": -10001},
        chat_id=7,
    )

    await handle_garage_forward_input(update, context, session, state, "@not_channel")

    assert added_sources == []
    assert replies == ["来源必须是频道，群组或私聊不能作为车库转发来源。"]


@pytest.mark.asyncio
async def test_handle_garage_forward_audit_routes_with_short_code(monkeypatch):
    calls: list[tuple[int, str]] = []

    async def fake_show(update, context, chat_id: int, *, result: str = "all"):
        calls.append((chat_id, result))

    monkeypatch.setattr(admin_handler._admin_handler, "_show_garage_forward_audit_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}))

    await admin_handler._admin_handler._handle_garage_forward(
        update,
        context,
        -100123,
        CallbackParser.parse("gfw:audit:-100123:k"),
    )

    assert calls == [(-100123, "skipped")]
