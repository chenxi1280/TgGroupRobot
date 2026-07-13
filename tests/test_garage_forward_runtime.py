from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.admin_handler import handle_garage_forward_input
from backend.features.garage import garage_forward_handler as forward_handler
from backend.features.garage.garage_forward_handler import garage_forward_channel_post_handler
from backend.features.garage.services.garage_forward_service import GarageForwardService
from backend.features.garage.services.garage_features_service import TeacherSearchService
from backend.platform.delivery import DeliveryOutcome
from backend.platform.state import state_service
from backend.shared.callback_parser import CallbackParser


class _Session:
    def __init__(self):
        self.added: list[object] = []

    def add(self, item):
        self.added.append(item)

    async def execute(self, stmt):
        # 返回空结果，用于 update_last_seen_message_id 等查询
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )

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
    events: list[tuple[str, int]] = []
    plan = SimpleNamespace(
        delivery_id=77,
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
    )

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="all", keyword_rules=[]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_reserve(db, *, dest_chat_id, post, reply_markup):
        events.append(("reserve", dest_chat_id))
        return plan

    async def fake_execute(context, db, *, plan):
        events.append(("execute", plan.delivery_id))
        return DeliveryOutcome.success(999)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(forward_handler, "_reserve_forward_delivery", fake_reserve)
    monkeypatch.setattr(forward_handler, "_execute_forward_delivery", fake_execute)

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
        bot=SimpleNamespace(),
    )

    await garage_forward_channel_post_handler(update, context)

    assert events == [("reserve", -20001), ("execute", 77)]


@pytest.mark.asyncio
async def test_garage_forward_channel_post_indexes_teacher_for_destination(monkeypatch):
    indexed: list[dict[str, object]] = []

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="all", keyword_rules=[]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_index(session, **kwargs):
        indexed.append(kwargs)
        return SimpleNamespace(indexed=True, reason=None, user_id=77, username="jt37373", label_count=6)

    async def fake_copy_message(*, chat_id, from_chat_id, message_id, reply_markup=None):
        return SimpleNamespace(message_id=999)

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_reserve(*args, **kwargs):
        return None

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(GarageForwardService, "append_audit", fake_noop)
    monkeypatch.setattr(TeacherSearchService, "index_channel_post_teacher_profile", fake_index)
    monkeypatch.setattr(forward_handler, "_reserve_forward_delivery", fake_reserve)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-10001, type="channel"),
        effective_message=SimpleNamespace(
            message_id=321,
            text=None,
            caption="【详细标签】：#嫩妹车 #御姐车 #自聊 #态度车 #颜值车 #深喉\n【联系方式】： @jt37373",
            photo=["p"],
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

    assert indexed == [
        {
            "chat_id": -20001,
            "channel_id": -10001,
            "message_id": 321,
            "text": "【详细标签】：#嫩妹车 #御姐车 #自聊 #态度车 #颜值车 #深喉\n【联系方式】： @jt37373",
        }
    ]


@pytest.mark.asyncio
async def test_garage_forward_channel_post_indexes_linked_group_without_forward_source(monkeypatch):
    indexed: list[dict[str, object]] = []
    copied_calls: list[dict[str, object]] = []

    async def fake_list_destinations_by_source(session, source_channel_id):
        return []

    async def fake_index(session, **kwargs):
        indexed.append(kwargs)
        return SimpleNamespace(indexed=True, reason="pending_bind", user_id=None, username="jt37373", label_count=6)

    async def fake_get_chat(chat_id):
        assert chat_id == -10001
        return SimpleNamespace(
            id=-10001,
            linked_chat_id=-20001,
            username="tianjin_garage",
            title="天津音乐学院车库",
        )

    async def fake_copy_message(**kwargs):
        copied_calls.append(kwargs)
        return SimpleNamespace(message_id=999)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(TeacherSearchService, "index_channel_post_teacher_profile", fake_index)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-10001, type="channel"),
        effective_message=SimpleNamespace(
            message_id=321,
            text=None,
            caption="【详细标签】：#颜值车 #深喉\n【所在位置】：#河西区\n【联系方式】： @jt37373",
            photo=["p"],
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
        bot=SimpleNamespace(copy_message=fake_copy_message, get_chat=fake_get_chat),
    )

    await garage_forward_channel_post_handler(update, context)

    assert copied_calls == []
    assert indexed == [
        {
            "chat_id": -20001,
            "channel_id": -10001,
            "message_id": 321,
            "text": "【详细标签】：#颜值车 #深喉\n【所在位置】：#河西区\n【联系方式】： @jt37373",
            "channel_username": "tianjin_garage",
            "channel_title": "天津音乐学院车库",
        }
    ]


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

    async def fake_copy_message(*, chat_id, from_chat_id, message_id):
        copied_calls.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=1000)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)

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

    async def fake_reserve(*args, **kwargs):
        return None

    async def fake_append_audit(session, *, chat_id, source_channel_id, action, result, reason=None, source_message_id=None):
        audits.append((chat_id, action, result, reason))

    async def fake_copy_message(*, chat_id, from_chat_id, message_id):
        copied_calls.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=1000)

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(GarageForwardService, "append_audit", fake_append_audit)
    monkeypatch.setattr(forward_handler, "_reserve_forward_delivery", fake_reserve)

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

    async def fake_clear_private_input_state(session, user_id):
        clear_calls.append((user_id, user_id))

    async def fake_show(update, context, chat_id):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(state_service, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(state_service, "clear_private_input_state", fake_clear_private_input_state)
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


@pytest.mark.asyncio
async def test_handle_garage_forward_manual_audit_cleanup(monkeypatch):
    cleanup_calls: list[tuple[int, str | None]] = []
    shown: list[tuple[int, str]] = []
    answers: list[str] = []

    async def fake_purge_expired_audits(session, *, chat_id: int | None = None, result: str | None = None, **kwargs):
        cleanup_calls.append((chat_id, result))
        return 3

    async def fake_show(update, context, chat_id: int, *, result: str = "all"):
        shown.append((chat_id, result))

    async def fake_answer(update, text: str, show_alert: bool = False):
        answers.append(text)

    monkeypatch.setattr(GarageForwardService, "purge_expired_audits", fake_purge_expired_audits)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_garage_forward_audit_menu", fake_show)
    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": SimpleNamespace(session_factory=_SessionFactory())}))

    await admin_handler._admin_handler._handle_garage_forward(
        update,
        context,
        -100123,
        CallbackParser.parse("gfw:audit_cleanup:-100123:f"),
    )

    assert cleanup_calls == [(-100123, "failed")]
    assert answers == ["已清理 3 条超期日志。"]
    assert shown == [(-100123, "failed")]


# ----------------------------------------------------------------------
# P2.2-G 车库转发恢复：实时持久化执行 + GarageForwardRetryTask 调度任务
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_garage_forward_reserves_snapshot_before_execution(monkeypatch):
    events: list[tuple[str, object]] = []
    snapshot = {"inline_keyboard": [[{"text": "详情", "url": "https://example.com"}]]}
    markup = SimpleNamespace(to_dict=lambda: snapshot)
    plan = SimpleNamespace(
        delivery_id=77,
        chat_id=-20001,
        source_channel_id=-10001,
        source_message_id=321,
    )

    async def fake_list_destinations_by_source(session, source_channel_id):
        return [
            (
                SimpleNamespace(chat_id=-20001, enabled=True, sync_mode="all", keyword_rules=[]),
                SimpleNamespace(source_channel_id=-10001, source_name="车库源", enabled=True),
            )
        ]

    async def fake_reserve(db, *, dest_chat_id, post, reply_markup):
        events.append(("reserve", reply_markup.to_dict()))
        return plan

    async def fake_execute(context, db, *, plan):
        events.append(("execute", plan.delivery_id))
        return DeliveryOutcome.retryable_failure("rate_limit", "later")

    monkeypatch.setattr(GarageForwardService, "list_destinations_by_source", fake_list_destinations_by_source)
    monkeypatch.setattr(forward_handler, "_build_reply_markup", lambda setting: markup)
    monkeypatch.setattr(forward_handler, "_reserve_forward_delivery", fake_reserve)
    monkeypatch.setattr(forward_handler, "_execute_forward_delivery", fake_execute)

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
        bot=SimpleNamespace(),
    )

    await garage_forward_channel_post_handler(update, context)

    assert events == [("reserve", snapshot), ("execute", 77)]


@pytest.mark.asyncio
async def test_garage_forward_retry_task_delegates_to_worker(monkeypatch):
    from backend.platform.scheduler.tasks import garage_forward_retry_task as task_module

    events: list[str] = []

    class FakeWorker:
        def __init__(self, dependencies) -> None:
            events.append("build")

        async def run(self):
            events.append("run")

    monkeypatch.setattr(task_module, "GarageForwardWorker", FakeWorker)
    app = SimpleNamespace(bot=SimpleNamespace(), bot_data={"db": object()})

    await task_module.GarageForwardRetryTask().execute(app)

    assert events == ["build", "run"]


@pytest.mark.asyncio
async def test_garage_forward_retry_task_exposes_missing_database() -> None:
    from backend.platform.scheduler.tasks.garage_forward_retry_task import GarageForwardRetryTask

    with pytest.raises(RuntimeError, match="database"):
        await GarageForwardRetryTask().execute(SimpleNamespace(bot=object(), bot_data={}))
