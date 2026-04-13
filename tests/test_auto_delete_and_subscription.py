from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops.auto_delete_handler import auto_delete_handler
import backend.features.group_ops.auto_delete_handler as auto_delete_handler_module
from backend.features.admin.ui.auto_delete import auto_delete_config_keyboard
from backend.platform.db.schema.models.core import ChatSubscription, SubscriptionPlan
from backend.platform.db.schema.models.enums import SubscriptionStatus
from backend.features.subscription.services import subscription_service
from backend.features.subscription.services.subscription_service import ensure_default_plans, get_or_create_chat_subscription


def test_auto_delete_keyboard_uses_expected_callbacks() -> None:
    settings = SimpleNamespace(
        auto_delete_enabled=True,
        auto_delete_join=False,
        auto_delete_left=True,
        auto_delete_pinned=False,
        auto_delete_avatar=True,
        auto_delete_title=False,
        auto_delete_anonymous=True,
    )

    keyboard = auto_delete_config_keyboard(settings, -100123)
    rows = keyboard.inline_keyboard

    assert rows[0][0].callback_data == "autodel:noop:join:-100123"
    assert rows[0][1].callback_data == "autodel:set:join:1:-100123"
    assert rows[0][2].callback_data == "autodel:set:join:0:-100123"
    assert rows[1][0].callback_data == "autodel:noop:left:-100123"
    assert rows[-1][0].callback_data == "adm:menu:main:-100123"


@pytest.mark.asyncio
async def test_auto_delete_handler_deletes_join_message_when_enabled(monkeypatch) -> None:
    calls: list[str] = []

    class FakeMessage:
        message_id = 77
        new_chat_members = [SimpleNamespace(id=1)]
        left_chat_member = None
        pinned_message = None
        forum_topic_created = False
        forum_topic_edited = False
        forum_topic_closed = False
        general_forum_topic_hidden = False
        users_shared = None
        chat_shared = None
        is_automatic_forward = False
        successful_payment = None
        connected_website = None
        proximity_alert_triggered = None
        video_chat_scheduled = False
        video_chat_ended = False
        video_chat_participants_invited = False
        new_chat_title = None
        new_chat_photo = None
        delete_chat_photo = False
        from_user = None

        async def delete(self) -> None:
            calls.append("delete")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def commit(self) -> None:
            calls.append("commit")

    class FakeDB:
        def __init__(self) -> None:
            self.session_factory = lambda: FakeSession()

    async def fake_ensure(session, chat_id, chat_type=None, title=None, user_id=None, username=None, first_name=None, last_name=None, language_code=None):
        return SimpleNamespace(
            auto_delete_enabled=True,
            auto_delete_join=True,
            auto_delete_left=False,
            auto_delete_pinned=False,
            auto_delete_avatar=False,
            auto_delete_title=False,
            auto_delete_anonymous=False,
        )

    monkeypatch.setattr(auto_delete_handler_module.ModuleSettingsService, "ensure", fake_ensure)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="测试群"),
        effective_message=FakeMessage(),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": FakeDB()}))

    await auto_delete_handler(update, context)

    assert calls == ["commit", "delete"]


@pytest.mark.asyncio
async def test_ensure_default_plans_creates_missing_plans(monkeypatch) -> None:
    added: list[SubscriptionPlan] = []

    class FakeSession:
        async def flush(self) -> None:
            return None

        def add(self, entity) -> None:
            added.append(entity)

    async def fake_get_by_filters(session, model, filters):
        return None

    monkeypatch.setattr(subscription_service.ServiceBase, "_get_by_filters", fake_get_by_filters)

    await ensure_default_plans(FakeSession())

    assert {plan.code for plan in added} == {"free", "pro_monthly", "pro_yearly"}


@pytest.mark.asyncio
async def test_get_or_create_chat_subscription_creates_free_plan_subscription(monkeypatch) -> None:
    created: list[object] = []
    free_plan = SubscriptionPlan(
        id=1,
        code="free",
        name="免费版",
        price_cents=0,
        duration_days=0,
        feature_flags={},
    )

    class FakeSession:
        async def flush(self) -> None:
            return None

        def add(self, entity) -> None:
            created.append(entity)

    async def fake_get_by_filters(session, model, filters):
        if model is SubscriptionPlan and filters.get("code") == "free":
            return free_plan
        if model is ChatSubscription:
            return None
        return None

    monkeypatch.setattr(subscription_service.ServiceBase, "_get_by_filters", fake_get_by_filters)

    sub = await get_or_create_chat_subscription(FakeSession(), -100123)

    assert sub.chat_id == -100123
    assert sub.plan_id == 1
    assert sub.status == SubscriptionStatus.active.value
    assert any(isinstance(entity, ChatSubscription) for entity in created)
