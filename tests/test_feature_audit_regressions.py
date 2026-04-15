from __future__ import annotations

from types import SimpleNamespace
import datetime as dt

import pytest

from backend.features.admin import admin_handler
from backend.features.automation import ads_handler
from backend.features.group_ops import group_message_handler
from backend.features.group_ops.group_hooks import controls as group_controls
from backend.features.admin import points_config_handler
from backend.features.verification import verification_handler
from backend.features.automation.scheduled_message_handler import ScheduledMessageHandler
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.callback_parser import CallbackParser


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def flush(self):
        return None

    async def get(self, model, pk):
        return None


class _Db:
    def __init__(self, session: _Session | None = None) -> None:
        self._session = session or _Session()

    def session_factory(self):
        return self._session


@pytest.mark.asyncio
async def test_car_review_reuses_reply_photo_as_fallback():
    reply_photo = [SimpleNamespace(file_id="reply-photo-id")]
    message = SimpleNamespace(photo=[], reply_to_message=SimpleNamespace(photo=reply_photo))

    media_ids = group_message_handler._extract_car_review_media_file_ids(message)

    assert media_ids == ["reply-photo-id"]


@pytest.mark.asyncio
async def test_car_review_duplicate_audit_is_blocked(monkeypatch):
    answered: list[tuple[str, bool]] = []
    rendered: list[tuple[int, str]] = []

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(approver_user_id=None, reward_points=0)

    async def fake_get_report(session, chat_id: int, report_id: int):
        return SimpleNamespace(report_id=report_id, report_status="published")

    async def fake_answer(update, text: str, show_alert: bool = False):
        answered.append((text, show_alert))

    async def fake_show_detail(update, context, chat_id: int, report_id: int, status: str = "all"):
        rendered.append((report_id, status))

    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(CarReviewService, "get_report", fake_get_report)
    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_car_review_report_detail", fake_show_detail)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))
    callback_data = CallbackParser.parse("crv:report:-100123:approve:3:p")

    await admin_handler._admin_handler._handle_car_review(update, context, -100123, callback_data)

    assert answered == [("该报告当前状态不可再次审核", True)]
    assert rendered == [(3, "pending")]


@pytest.mark.asyncio
async def test_car_review_non_admin_approver_does_not_block_real_admin(monkeypatch):
    answered: list[tuple[str, bool]] = []
    detail_calls: list[tuple[int, str]] = []
    approved: dict[str, int] = {}

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(approver_user_id=999, reward_points=0)

    report = SimpleNamespace(
        report_id=3,
        chat_id=-100123,
        teacher_user_id=None,
        author_user_id=None,
        report_status="pending",
        published_message_id=None,
        updated_at=None,
    )

    async def fake_get_report(session, chat_id: int, report_id: int):
        return report

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        approved["approver_checked_for"] = user_id
        return False

    async def fake_approve_report(session, chat_id: int, report_id: int, approver_user_id: int):
        approved["approver_user_id"] = approver_user_id
        report.report_status = "approved"
        return report

    async def fake_answer(update, text: str, show_alert: bool = False):
        answered.append((text, show_alert))

    async def fake_show_detail(update, context, chat_id: int, report_id: int, status: str = "all"):
        detail_calls.append((report_id, status))

    async def fake_publish(*args, **kwargs):
        return None

    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(CarReviewService, "get_report", fake_get_report)
    monkeypatch.setattr(CarReviewService, "approve_report", fake_approve_report)
    monkeypatch.setattr(admin_handler, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_car_review_report_detail", fake_show_detail)
    monkeypatch.setattr(admin_handler, "_publish_car_review_report", fake_publish, raising=False)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))
    callback_data = CallbackParser.parse("crv:report:-100123:approve:3:p")

    await admin_handler._admin_handler._handle_car_review(update, context, -100123, callback_data)

    assert approved == {"approver_checked_for": 999, "approver_user_id": 7}
    assert answered == [("报告已通过审核，当前未执行自动发布", False)]
    assert detail_calls == [(3, "pending")]


@pytest.mark.asyncio
async def test_points_legacy_todo_entries_redirect_to_real_flow(monkeypatch):
    rendered: list[str] = []
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), user_data={})

    async def fake_safe_edit(q, text: str, **kwargs):
        rendered.append(text)

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            sign_enabled=True,
            sign_points=5,
            sign_consecutive_days=7,
            sign_consecutive_bonus=10,
            message_points_enabled=False,
            message_points=2,
            message_points_daily_limit=None,
            message_min_length=6,
            invite_points_enabled=False,
            invite_points=3,
            invite_points_daily_limit=20,
            points_alias="积分",
            points_rank_alias="积分排行",
        )

    monkeypatch.setattr(points_config_handler, "_safe_edit_message", fake_safe_edit)
    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    q = SimpleNamespace(
        data="pts:todo:clear_points:-1001",
        answer=lambda *args, **kwargs: None,
    )

    async def fake_answer(*args, **kwargs):
        return None

    q.answer = fake_answer
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(type="private"),
    )

    result = await points_config_handler._points_config_handler.process(update, context, -1001)

    assert result == points_config_handler.WAIT_VALUE
    assert context.user_data == {"points_edit_field": "clear_points", "points_edit_chat_id": -1001}
    assert rendered and "请输入 CONFIRM" in rendered[0]


@pytest.mark.asyncio
async def test_ads_create_start_opens_new_item_detail(monkeypatch):
    shown: dict[str, int] = {}

    async def fake_resolve_target_chat_id(update, context):
        return -1005566

    async def fake_ensure(*args, **kwargs):
        return None

    async def fake_create_rotation_item(session, **kwargs):
        return SimpleNamespace(id=321)

    monkeypatch.setattr(ads_handler, "_resolve_ads_target_chat_id", fake_resolve_target_chat_id)
    monkeypatch.setattr(ads_handler.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(ads_handler, "create_rotation_item", fake_create_rotation_item)

    async def fake_show_detail(update, context, target_chat_id: int, item_id: int):
        shown["chat_id"] = target_chat_id
        shown["item_id"] = item_id

    monkeypatch.setattr(ads_handler._ads_handler, "show_detail", fake_show_detail)

    class _Q:
        data = "ads:create"

        async def answer(self):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(id=9001, type="private", title=None),
        effective_user=SimpleNamespace(
            id=42,
            username="tester",
            first_name="Test",
            last_name=None,
            language_code="zh-CN",
        ),
    )

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await ads_handler.ads_create_start_callback(update, context)

    assert shown == {"chat_id": -1005566, "item_id": 321}


@pytest.mark.asyncio
async def test_points_tasks_view_renders(monkeypatch):
    rendered: list[str] = []
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), user_data={})

    async def fake_safe_edit(q, text: str, **kwargs):
        rendered.append(text)

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            sign_enabled=True,
            sign_points=5,
            message_points_enabled=True,
            message_points=2,
            message_points_daily_limit=10,
            message_min_length=6,
            invite_points_enabled=False,
            invite_points=1,
            invite_points_daily_limit=None,
            points_alias="积分",
            points_rank_alias="积分排行",
        )

    monkeypatch.setattr(points_config_handler, "_safe_edit_message", fake_safe_edit)
    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    q = SimpleNamespace(
        data="pts:view:tasks:-1001",
        answer=lambda *args, **kwargs: None,
    )

    async def fake_answer(*args, **kwargs):
        return None

    q.answer = fake_answer
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=7),
    )

    await points_config_handler._points_config_handler.process(update, context, -1001)

    assert rendered and "积分任务" in rendered[0]


@pytest.mark.asyncio
async def test_quick_publish_text_updates_draft(monkeypatch):
    from backend.platform.telegram.private_config_handler import PrivateConfigHandler

    calls: list[int] = []

    async def fake_clear_state(session, chat_id: int, user_id: int):
        calls.append(chat_id)

    async def fake_show_menu(update, context, chat_id: int):
        calls.append(chat_id)

    monkeypatch.setattr("backend.platform.state.state_service.clear_user_state", fake_clear_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_quick_publish_menu", fake_show_menu)

    handler = PrivateConfigHandler()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), user_data={})
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        effective_message=SimpleNamespace(reply_text=lambda *args, **kwargs: None),
    )
    state = SimpleNamespace(
        chat_id=7,
        state_data={"target_chat_id": -1001, "field": "text"},
    )

    await handler._handle_quick_publish_input(update, context, _Session(), state, "hello world")

    draft = context.user_data["quick_publish_draft"][str(-1001)]
    assert draft["text"] == "hello world"
    assert calls == [7, 7, -1001]


@pytest.mark.asyncio
async def test_quick_publish_home_requires_permission_service(monkeypatch):
    from backend.shared.services import permission_service

    calls: list[tuple[str, int]] = []

    async def fake_require_manage(context, chat_id: int, user_id: int, capability: str = "manage"):
        calls.append(("perm", chat_id))
        return True, None

    async def fake_show_menu(update, context, chat_id: int):
        calls.append(("menu", chat_id))

    monkeypatch.setattr(permission_service.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_quick_publish_menu", fake_show_menu)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        callback_query=SimpleNamespace(answer=lambda *args, **kwargs: None),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), user_data={})
    callback_data = CallbackParser.parse("qpub:home:-1001")

    await admin_handler._admin_handler._handle_quick_publish(update, context, -1001, callback_data)

    assert ("perm", -1001) in calls
    assert ("menu", -1001) in calls


@pytest.mark.asyncio
async def test_ads_menu_opens_when_paid_logic_disabled(monkeypatch):
    opened: list[int] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_show_menu(update, context, chat_id: int):
        opened.append(chat_id)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(ads_handler._ads_handler, "show_menu", fake_show_menu)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), user_data={})

    await admin_handler._admin_handler._show_ads_menu(update, context, -1001)

    assert opened == [-1001]


@pytest.mark.asyncio
async def test_punishment_policy_preset_updates_actions(monkeypatch):
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class _FakeDb:
        def session_factory(self):
            return _FakeSession()

    settings = SimpleNamespace(
        anti_spam_action="delete",
        anti_flood_action="delete",
        moderation_action="delete",
        verification_timeout_action="kick",
    )

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show_menu(update, context, chat_id: int):
        return None

    monkeypatch.setattr("backend.features.admin.moderation.config_actions.get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_punishment_policy_menu", fake_show_menu)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))
    callback_data = CallbackParser.parse("adm:punish:-1001:preset:mute")

    await admin_handler._admin_handler._handle_punishment_policy(update, context, -1001, callback_data)

    assert settings.anti_spam_action == "mute"
    assert settings.anti_flood_action == "mute"
    assert settings.moderation_action == "mute"
    assert settings.verification_timeout_action == "mute"


@pytest.mark.asyncio
async def test_scheduled_edit_field_keeps_target_chat_id_in_private_state(monkeypatch):
    started: dict[str, object] = {}
    rendered: list[tuple[str, object]] = []
    handler = ScheduledMessageHandler()

    async def fake_check_permission(update, context, chat_id: int):
        return True

    async def fake_get_task(session, chat_id: int, task_id: str):
        return SimpleNamespace(task_id=task_id)

    async def fake_start(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        started.update(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "state_type": state_type,
                "state_data": state_data,
            }
        )

    async def fake_safe_edit(update, text: str, reply_markup=None):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(handler, "_check_permission", fake_check_permission)
    monkeypatch.setattr(
        ads_handler.ConversationStateService,
        "start",
        fake_start,
        raising=False,
    )
    monkeypatch.setattr(
        verification_handler,
        "ConversationStateService",
        verification_handler.ConversationStateService,
        raising=False,
    )
    monkeypatch.setattr(
        __import__("backend.features.automation.scheduled_message_handler", fromlist=["ConversationStateService"]).ConversationStateService,
        "start",
        fake_start,
    )
    monkeypatch.setattr(
        __import__("backend.features.automation.services.scheduled_message_service", fromlist=["ScheduledMessageService"]).ScheduledMessageService,
        "get_task_in_chat_or_404",
        fake_get_task,
    )
    monkeypatch.setattr(handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await handler.edit_field(update, context, -1005566, "task-1", "text")

    assert started == {
        "chat_id": 9001,
        "user_id": 42,
        "state_type": ConversationStateType.sm_edit_text.value,
        "state_data": {"task_id": "task-1", "target_chat_id": -1005566},
    }
    assert rendered and rendered[0][0].startswith("✏️ 编辑文本")


@pytest.mark.asyncio
async def test_scheduled_button_fsm_accepts_line_format(monkeypatch):
    handler = ScheduledMessageHandler()
    session = _Session()
    cleared: list[tuple[int, int]] = []
    updated: dict[str, object] = {}
    details: list[tuple[int, str, str | None]] = []

    async def fake_get(session_obj, chat_id: int, user_id: int):
        return SimpleNamespace(
            state_type=ConversationStateType.sm_edit_buttons.value,
            state_data={"task_id": "task-1", "target_chat_id": -1005566},
        )

    async def fake_clear(session_obj, chat_id: int, user_id: int):
        cleared.append((chat_id, user_id))

    async def fake_update_buttons(session_obj, task_id: str, buttons: list):
        updated["task_id"] = task_id
        updated["buttons"] = buttons
        return SimpleNamespace(task_id=task_id, buttons=buttons)

    async def fake_show_detail(update, context, target_chat_id: int, task_id: str, toast: str | None = None):
        details.append((target_chat_id, task_id, toast))

    monkeypatch.setattr(
        __import__("backend.features.automation.scheduled_message_handler", fromlist=["ConversationStateService"]).ConversationStateService,
        "get",
        fake_get,
    )
    monkeypatch.setattr(
        __import__("backend.features.automation.scheduled_message_handler", fromlist=["ConversationStateService"]).ConversationStateService,
        "clear",
        fake_clear,
    )
    monkeypatch.setattr(
        __import__("backend.features.automation.services.scheduled_message_service", fromlist=["ScheduledMessageService"]).ScheduledMessageService,
        "update_task_buttons",
        fake_update_buttons,
    )
    monkeypatch.setattr(handler, "show_detail", fake_show_detail)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_message=SimpleNamespace(reply_text=None),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db(session)}))

    await handler.handle_fsm_input(
        update,
        context,
        -1005566,
        42,
        "官网|example.com ; 帮助|https://help.example.com",
    )

    assert updated == {
        "task_id": "task-1",
        "buttons": [[
            {"text": "官网", "url": "https://example.com"},
            {"text": "帮助", "url": "https://help.example.com"},
        ]],
    }
    assert cleared == [(9001, 42)]
    assert details == [(-1005566, "task-1", "✅ 按钮已保存")]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_points_level_unknown_op_uses_specific_message(monkeypatch):
    answered: list[tuple[str, bool]] = []

    async def fake_answer(update, text: str, show_alert: bool = False):
        answered.append((text, show_alert))

    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)

    await admin_handler._admin_handler._handle_points_level(
        SimpleNamespace(),
        SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()})),
        -100123,
        CallbackParser.parse("adm:lvl:-100123:unknown"),
    )

    assert answered == [("未识别的积分等级操作，请刷新页面后重试", True)]


@pytest.mark.asyncio
async def test_force_subscribe_unknown_input_uses_specific_message(monkeypatch):
    answered: list[tuple[str, bool]] = []

    async def fake_answer(update, text: str, show_alert: bool = False):
        answered.append((text, show_alert))

    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)

    await admin_handler._admin_handler._handle_force_subscribe(
        SimpleNamespace(effective_user=SimpleNamespace(id=42)),
        SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()})),
        -100123,
        CallbackParser.parse("adm:forcesub:-100123:input:unknown"),
    )

    assert answered == [("未识别的强制订阅配置项，请返回后重试", True)]


@pytest.mark.asyncio
async def test_new_member_limit_blocks_media_and_links(monkeypatch):
    deleted: list[bool] = []
    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode=None):
            sent.append((chat_id, text))

            async def delete():
                return None

            return SimpleNamespace(delete=delete)

    async def fake_get_member_joined_at(db, chat_id: int, user_id: int):
        return dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)

    async def fake_delete():
        deleted.append(True)

    monkeypatch.setattr(group_controls, "_get_member_joined_at", fake_get_member_joined_at)

    context = SimpleNamespace(bot=FakeBot(), application=SimpleNamespace(bot_data={"db": _Db()}))
    chat = SimpleNamespace(id=-1001)
    user = SimpleNamespace(id=7, full_name="测试用户")
    message = SimpleNamespace(
        text="访问 https://example.com",
        caption=None,
        entities=[SimpleNamespace(type="url")],
        caption_entities=[],
        photo=[SimpleNamespace(file_id="p1")],
        message_id=11,
    )
    message.delete = fake_delete

    settings = SimpleNamespace(
        new_member_limit_enabled=True,
        new_member_limit_window_seconds=3600,
        new_member_limit_block_media=True,
        new_member_limit_block_links=True,
        new_member_limit_text_only=False,
        new_member_limit_delete_message=True,
        new_member_limit_warn_enabled=True,
        new_member_limit_warn_text="新成员需等待 {duration} 才可发言。",
        new_member_limit_warn_delete_after_seconds=0,
    )

    blocked = await group_message_handler._process_new_member_limit(
        context,
        _Db(),
        chat,
        user,
        message,
        settings,
    )

    assert blocked is True
    assert deleted == [True]
    assert sent and "新成员需等待" in sent[0][1]


@pytest.mark.asyncio
async def test_night_mode_blocks_messages(monkeypatch):
    deleted: list[bool] = []
    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode=None):
            sent.append((chat_id, text))

            async def delete():
                return None

            return SimpleNamespace(delete=delete)

    async def fake_delete():
        deleted.append(True)

    monkeypatch.setattr(group_controls, "_is_night_time", lambda settings: True)

    context = SimpleNamespace(bot=FakeBot(), application=SimpleNamespace(bot_data={"db": _Db()}))
    chat = SimpleNamespace(id=-1001)
    user = SimpleNamespace(id=7, full_name="测试用户")
    message = SimpleNamespace(message_id=12)
    message.delete = fake_delete

    settings = SimpleNamespace(
        night_mode_enabled=True,
        night_mode_exempt_admin=True,
        night_mode_whitelist_user_ids=[],
        night_mode_delete_message=True,
        night_mode_warn_enabled=True,
        night_mode_warn_text="夜间模式中",
        night_mode_warn_delete_after_seconds=0,
    )

    blocked = await group_message_handler._process_night_mode(
        context,
        chat,
        user,
        message,
        settings,
        is_admin=False,
    )

    assert blocked is True
    assert deleted == [True]
    assert sent and sent[0][1] == "夜间模式中"


@pytest.mark.asyncio
async def test_new_member_without_invite_metadata_does_not_award_points(monkeypatch):
    awarded_calls: list[object] = []

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            welcome_enabled=False,
            welcome_message=None,
            language="zh-CN",
            verification_enabled=True,
            verification_timeout_seconds=60,
            verification_mode="button",
            verification_restrict_can_send=False,
            invite_link_notify=False,
        )

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_upsert(*args, **kwargs):
        return None

    async def fake_send_for_mode(*args, **kwargs):
        return False

    async def fake_burst_guard(*args, **kwargs):
        return False

    async def fake_join_spam_guard(*args, **kwargs):
        return False

    async def fake_track_and_award_invite(*args, **kwargs):
        awarded_calls.append(kwargs)
        return True, True, None

    async def fake_create_challenge(*args, **kwargs):
        return SimpleNamespace(token="token-1", question="1+1=?", solved=False, timeout_handled=False)

    async def fake_t(*args, **kwargs):
        return "验证提示"

    monkeypatch.setattr(verification_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(verification_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(verification_handler, "_upsert_chat_member_join", fake_upsert)
    monkeypatch.setattr(verification_handler.WelcomeService, "send_for_mode", fake_send_for_mode)
    monkeypatch.setattr(verification_handler, "_handle_join_burst_guard", fake_burst_guard)
    monkeypatch.setattr(verification_handler, "_handle_join_spam_guard", fake_join_spam_guard)
    monkeypatch.setattr(verification_handler, "track_and_award_invite", fake_track_and_award_invite)
    monkeypatch.setattr(verification_handler, "create_or_replace_challenge", fake_create_challenge)
    monkeypatch.setattr(verification_handler, "t", lambda *args, **kwargs: "验证提示")

    class _Bot:
        async def restrict_chat_member(self, **kwargs):
            return None

        async def send_message(self, **kwargs):
            return None

    member = SimpleNamespace(
        id=99,
        username="newbie",
        first_name="New",
        last_name=None,
        language_code="zh-CN",
        mention_html=lambda: "<a>New</a>",
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="测试群"),
        effective_message=SimpleNamespace(new_chat_members=[member]),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _Db()}),
        bot=_Bot(),
        user_data={},
    )

    await verification_handler.new_members_handler(update, context)

    assert awarded_calls == []


@pytest.mark.asyncio
async def test_invite_link_join_hint_handler_caches_reliable_metadata():
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
    update = SimpleNamespace(
        chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=-100123),
            invite_link=SimpleNamespace(invite_link="https://t.me/+demo"),
            new_chat_member=SimpleNamespace(user=SimpleNamespace(id=99)),
        )
    )

    await verification_handler.invite_link_join_hint_handler(update, context)

    assert context.application.bot_data["invite_join_hints"] == {
        (-100123, 99): {"invite_link": "https://t.me/+demo"}
    }


@pytest.mark.asyncio
async def test_new_member_with_cached_invite_hint_awards_points(monkeypatch):
    awarded_calls: list[dict] = []

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            welcome_enabled=False,
            welcome_message=None,
            language="zh-CN",
            verification_enabled=True,
            verification_timeout_seconds=60,
            verification_mode="button",
            verification_restrict_can_send=False,
            invite_link_notify=False,
        )

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_upsert(*args, **kwargs):
        return None

    async def fake_send_for_mode(*args, **kwargs):
        return False

    async def fake_burst_guard(*args, **kwargs):
        return False

    async def fake_join_spam_guard(*args, **kwargs):
        return False

    async def fake_track_and_award_invite(session, **kwargs):
        awarded_calls.append(kwargs)
        return True, True, None

    async def fake_create_challenge(*args, **kwargs):
        return SimpleNamespace(token="token-1", question="1+1=?", solved=False, timeout_handled=False)

    monkeypatch.setattr(verification_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(verification_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(verification_handler, "_upsert_chat_member_join", fake_upsert)
    monkeypatch.setattr(verification_handler.WelcomeService, "send_for_mode", fake_send_for_mode)
    monkeypatch.setattr(verification_handler, "_handle_join_burst_guard", fake_burst_guard)
    monkeypatch.setattr(verification_handler, "_handle_join_spam_guard", fake_join_spam_guard)
    monkeypatch.setattr(verification_handler, "track_and_award_invite", fake_track_and_award_invite)
    monkeypatch.setattr(verification_handler, "create_or_replace_challenge", fake_create_challenge)
    monkeypatch.setattr(
        verification_handler,
        "t",
        lambda *args, **kwargs: "验证提示",
    )

    class _LinkResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=77, chat_id=-100123, created_by_user_id=555, member_count=0)

    class _InviteSession(_Session):
        async def execute(self, stmt):
            return _LinkResult()

    class _Bot:
        async def restrict_chat_member(self, **kwargs):
            return None

        async def send_message(self, **kwargs):
            return None

    member = SimpleNamespace(
        id=99,
        username="newbie",
        first_name="New",
        last_name=None,
        language_code="zh-CN",
        mention_html=lambda: "<a>New</a>",
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="测试群"),
        effective_message=SimpleNamespace(new_chat_members=[member]),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _Db(_InviteSession()), "invite_join_hints": {(-100123, 99): {"invite_link": "https://t.me/+demo"}}}),
        bot=_Bot(),
        user_data={},
    )

    await verification_handler.new_members_handler(update, context)

    assert awarded_calls == [
        {
            "chat_id": -100123,
            "inviter_user_id": 555,
            "invited_user_id": 99,
            "invite_link_id": 77,
        }
    ]
    assert context.application.bot_data["invite_join_hints"] == {}
