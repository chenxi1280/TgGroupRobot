from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import admin_handler, ads_handler, group_message_handler, points_config_handler, verification_handler
from bot.handlers.scheduled_message_handler import ScheduledMessageHandler
from bot.models.enums import ConversationStateType
from bot.utils.callback_parser import CallbackParser


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

    from bot.services.integration.garage_features_service import CarReviewService

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

    from bot.services.integration.garage_features_service import CarReviewService

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
async def test_points_todo_entries_only_render_placeholder(monkeypatch):
    rendered: list[str] = []

    async def fake_safe_edit(q, text: str, **kwargs):
        rendered.append(text)

    monkeypatch.setattr(points_config_handler, "_safe_edit_message", fake_safe_edit)

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

    await points_config_handler._points_config_handler.process(update, SimpleNamespace(), -1001)

    assert rendered == [
        "💰 主积分 | 清空积分\n\n当前只有重构设计，基础版积分中心尚未接入这一能力。\n本轮已保留入口位置，避免首页继续和文档细节错位。"
    ]


@pytest.mark.asyncio
async def test_ads_create_start_keeps_target_chat_id_in_private_state(monkeypatch):
    started: dict[str, object] = {}
    edited: list[tuple[str, object]] = []

    async def fake_resolve_target_chat_id(update, context):
        return -1005566

    async def fake_ensure(*args, **kwargs):
        return None

    async def fake_start(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        started.update(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "state_type": state_type,
                "state_data": state_data,
            }
        )

    monkeypatch.setattr(ads_handler, "_resolve_ads_target_chat_id", fake_resolve_target_chat_id)
    monkeypatch.setattr(ads_handler.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(ads_handler.ConversationStateService, "start", fake_start)

    class _Q:
        data = "ads:create"

        async def answer(self):
            return None

        async def edit_message_text(self, text, **kwargs):
            edited.append((text, kwargs.get("reply_markup")))

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

    assert started == {
        "chat_id": 9001,
        "user_id": 42,
        "state_type": "ads_create_config",
        "state_data": {"target_chat_id": -1005566},
    }
    assert edited and "创建轮播广告" in edited[0][0]


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
        __import__("bot.handlers.scheduled_message_handler", fromlist=["ConversationStateService"]).ConversationStateService,
        "start",
        fake_start,
    )
    monkeypatch.setattr(
        __import__("bot.services.scheduled_message_service", fromlist=["ScheduledMessageService"]).ScheduledMessageService,
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
        "state_type": str(ConversationStateType.sm_edit_text),
        "state_data": {"task_id": "task-1", "target_chat_id": -1005566},
    }
    assert rendered and rendered[0][0].startswith("✏️ 编辑文本")


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
